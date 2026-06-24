"""Bash tool for executing shell commands with safety measures."""

import asyncio
import os
import platform
import signal

from pydantic import BaseModel

from ..safety import SafetyConfig, SecurityValidator
from . import Tool, ToolResult

_IS_WINDOWS = platform.system() == "Windows"


class BashParams(BaseModel):
    """Parameters for BashTool."""

    command: str


class BashTool(Tool):
    """Execute shell commands with security controls."""

    parameters_model = BashParams

    def __init__(
        self,
        timeout: int = 60,
        allowed_commands: list[str] | None = None,
        safety_config: SafetyConfig | None = None,
    ):
        super().__init__(
            name="bash",
            description="Execute shell commands in the terminal. Use for running programs, git commands, etc.",
        )
        self.timeout = min(
            timeout, safety_config.max_execution_time if safety_config else 60
        )
        self.allowed_commands = allowed_commands

        if safety_config:
            safety_config.allowed_commands = (
                allowed_commands or safety_config.allowed_commands
            )
            self.validator = SecurityValidator(safety_config)
        else:
            config = SafetyConfig(allowed_commands=allowed_commands or ["*"])
            self.validator = SecurityValidator(config)

    async def execute(self, command: str, **kwargs) -> ToolResult:
        """Execute the shell command with safety checks."""
        safe, reason = self.validator.check_command_safety(command)
        if not safe:
            return ToolResult(error=f"Command blocked: {reason}")

        if self.validator.requires_approval("bash"):
            approved = self.validator.get_approval("bash", command)
            if not approved:
                return ToolResult(error="Command requires approval")

        try:
            kwargs = dict(
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            if not _IS_WINDOWS:
                kwargs["preexec_fn"] = os.setsid

            proc = await asyncio.create_subprocess_shell(command, **kwargs)
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout
                )
            except asyncio.TimeoutError:
                try:
                    if _IS_WINDOWS:
                        proc.kill()
                    else:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError:
                    proc.kill()
                await proc.wait()
                return ToolResult(error=f"Command timed out after {self.timeout}s")

            output = stdout.decode(errors="replace") if stdout else ""
            err = stderr.decode(errors="replace") if stderr else ""

            original_len = len(output)
            output = output[:100000]
            if original_len > 100000:
                output += "\n\n[WARNING: Output heavily truncated (exceeded 100k characters)]"

            if proc.returncode != 0:
                return ToolResult(content=output + ("\n" + err if err else ""))
            return ToolResult(content=output)
        except Exception as e:
            return ToolResult(error=str(e))
