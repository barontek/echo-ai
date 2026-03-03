"""Git tool for version control operations."""

import asyncio
import os

from pydantic import BaseModel

from ..safety import SafetyConfig, SecurityValidator
from . import Tool, ToolResult


SAFE_GIT_COMMANDS = [
    "status",
    "diff",
    "log",
    "show",
    "branch",
    "fetch",
    "clone",
    "init",
    "add",
    "commit",
    "push",
    "pull",
    "merge",
    "rebase",
    "stash",
    "checkout",
    "reset",
    "cherry-pick",
    "tag",
    "describe",
    "rev-parse",
    "ls-files",
    "ls-tree",
    "cat-file",
    "rev-list",
    "shortlog",
    "config",
    "status",
]


class GitParams(BaseModel):
    """Parameters for GitTool."""

    command: str
    args: str = ""


class GitTool(Tool):
    """Execute git commands safely."""

    parameters_model = GitParams

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

    def _build_non_interactive_command(self, command: str, args: str) -> str:
        """Build a non-interactive git command with appropriate flags."""
        base_cmd = f"git {command}"

        # Add --no-pager to prevent pager from blocking
        if command not in ["clone"]:
            base_cmd = f"git --no-pager {command}"

        # Add --no-edit for commands that might open editor
        no_edit_commands = ["commit", "merge", "rebase"]
        if command in no_edit_commands:
            base_cmd += " --no-edit"

        # For commit, also add --allow-empty-message if needed
        if command == "commit":
            base_cmd += " --allow-empty-message"

        # Add any user-provided args
        if args:
            base_cmd += f" {args}"

        return base_cmd.strip()

    async def execute(self, command: str, args: str = "", **kwargs) -> ToolResult:
        """Execute a git command in non-interactive mode."""
        full_command = self._build_non_interactive_command(command, args)

        safe, reason = self.validator.check_command_safety(f"git {command}")
        if not safe:
            return ToolResult(error=f"Git command blocked: {reason}")

        if command not in SAFE_GIT_COMMANDS:
            return ToolResult(error=f"Git subcommand '{command}' is not allowed")

        # Environment variables to prevent interactive prompts
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_EDITOR"] = "true"
        env["GIT_SEQUENCE_EDITOR"] = "true"
        env["DEBIAN_FRONTEND"] = "noninteractive"

        try:
            proc = await asyncio.create_subprocess_shell(
                full_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.base_dir,
                env=env,
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
