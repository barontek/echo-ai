"""Bash tool for executing shell commands with safety measures."""

import asyncio
import os
import platform
import signal
from typing import Any

from pydantic import BaseModel

from ..constants import BASH_OUTPUT_MAX_CHARS
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
            merged_config = SafetyConfig(
                **{k: v for k, v in safety_config.__dict__.items() if not k.startswith("_")}
            )
            if allowed_commands is not None:
                merged_config.allowed_commands = allowed_commands
            self.validator = SecurityValidator(merged_config)
        else:
            config = SafetyConfig(allowed_commands=allowed_commands or ["*"])
            self.validator = SecurityValidator(config)

    async def execute(self, command: str, **kwargs) -> ToolResult:
        """Execute the shell command with safety checks."""
        safe, reason = self.validator.check_command_safety(command)
        if not safe:
            return ToolResult(error=f"Command blocked: {reason}")

        if self.validator.requires_approval("bash"):
            approved = await self.validator.get_approval_async("bash", command)
            if not approved:
                return ToolResult(error="Command requires approval")

        try:
            sp_kwargs: dict[str, Any] = {
                "stdout": asyncio.subprocess.PIPE,
                "stderr": asyncio.subprocess.PIPE,
                "stdin": asyncio.subprocess.DEVNULL,
            }
            if not _IS_WINDOWS:
                sp_kwargs["preexec_fn"] = os.setsid

            proc = await asyncio.create_subprocess_shell(command, **sp_kwargs)
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout
                )
            except asyncio.TimeoutError:
                try:
                    if _IS_WINDOWS or proc.pid is None:
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
            output = output[:BASH_OUTPUT_MAX_CHARS]
            if original_len > BASH_OUTPUT_MAX_CHARS:
                output += f"\n\n[WARNING: Output heavily truncated (exceeded {BASH_OUTPUT_MAX_CHARS} characters)]"

            combined = output
            if err:
                combined += "\n" + err if output else err
            if proc.returncode != 0:
                return ToolResult(content=combined)
            return ToolResult(content=combined)
        except Exception as e:
            return ToolResult(error=str(e))
