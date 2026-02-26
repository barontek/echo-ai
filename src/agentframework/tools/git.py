"""Git tool for version control operations."""

import asyncio
from typing import Any

from ..safety import SafetyConfig, SecurityValidator
from . import Tool, ToolResult


SAFE_GIT_COMMANDS = [
    "status", "diff", "log", "show", "branch", "fetch", "clone", "init",
    "add", "commit", "push", "pull", "merge", "rebase", "stash", "checkout",
    "reset", "cherry-pick", "tag", "describe", "rev-parse", "ls-files",
    "ls-tree", "cat-file", "rev-list", "shortlog", "config", "status",
]


class GitTool(Tool):
    """Execute git commands safely."""

    def __init__(self, base_dir: str = ".", safety_config: SafetyConfig | None = None):
        super().__init__(
            name="git",
            description="Execute git commands for version control.",
        )
        self.base_dir = base_dir
        if safety_config:
            self.validator = SecurityValidator(safety_config)
        else:
            config = SafetyConfig(workspace=base_dir, allowed_commands=["git"])
            self.validator = SecurityValidator(config)

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The git command to execute (e.g., 'status', 'diff')",
                },
                "args": {
                    "type": "string",
                    "description": "Additional arguments for the command",
                },
            },
            "required": ["command"],
        }

    async def execute(self, command: str, args: str = "", **kwargs) -> ToolResult:
        """Execute a git command."""
        full_command = f"git {command} {args}".strip()
        
        safe, reason = self.validator.check_command_safety(f"git {command}")
        if not safe:
            return ToolResult(error=f"Git command blocked: {reason}")

        if command not in SAFE_GIT_COMMANDS:
            return ToolResult(error=f"Git subcommand '{command}' is not allowed")

        try:
            proc = await asyncio.create_subprocess_shell(
                full_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.base_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

            output = stdout.decode(errors="replace") if stdout else ""
            err = stderr.decode(errors="replace") if stderr else ""

            if proc.returncode != 0:
                return ToolResult(content=output + ("\n" + err if err else ""))
            return ToolResult(content=output[:50000])
        except asyncio.TimeoutError:
            return ToolResult(error="Git command timed out")
        except Exception as e:
            return ToolResult(error=str(e))
