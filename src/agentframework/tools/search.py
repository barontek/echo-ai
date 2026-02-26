"""Glob and grep tools for searching files with workspace confinement."""

import re
from pathlib import Path
from typing import Any

from ..safety import SafetyConfig, SecurityValidator
from . import Tool, ToolResult


class GlobTool(Tool):
    """Find files by pattern with workspace confinement."""

    def __init__(self, base_dir: str = ".", safety_config: SafetyConfig | None = None):
        super().__init__(
            name="glob",
            description="Find files matching a glob pattern.",
        )
        self.base_dir = Path(base_dir).resolve()
        
        if safety_config:
            safety_config.workspace = str(self.base_dir)
            self.validator = SecurityValidator(safety_config)
        else:
            self.validator = SecurityValidator(SafetyConfig(workspace=str(self.base_dir)))

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The glob pattern to match (e.g., '**/*.py')",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, pattern: str, **kwargs) -> ToolResult:
        """Find matching files with safety checks."""
        if self.validator.is_blocked_extension(pattern):
            return ToolResult(error="Cannot search for blocked extension")

        if not self.validator.check_path_traversal(pattern):
            return ToolResult(error="Path traversal blocked")

        try:
            matches = list(self.base_dir.glob(pattern))
            matches = [m for m in matches if self.validator.check_path_traversal(str(m))]

            if not matches:
                return ToolResult(content=f"No files matching '{pattern}'")

            result = "\n".join(str(m.relative_to(self.base_dir)) for m in sorted(matches)[:100])
            return ToolResult(content=result)
        except Exception as e:
            return ToolResult(error=str(e))


class GrepTool(Tool):
    """Search file contents with workspace confinement."""

    def __init__(self, base_dir: str = ".", safety_config: SafetyConfig | None = None):
        super().__init__(
            name="grep",
            description="Search for a pattern in files.",
        )
        self.base_dir = Path(base_dir).resolve()
        
        if safety_config:
            safety_config.workspace = str(self.base_dir)
            self.validator = SecurityValidator(safety_config)
        else:
            self.validator = SecurityValidator(SafetyConfig(workspace=str(self.base_dir)))

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "The directory or file to search in (default: '.')",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, pattern: str, path: str = ".", **kwargs) -> ToolResult:
        """Search for pattern in files with safety checks."""
        if not self.validator.check_path_traversal(path):
            return ToolResult(error="Path traversal blocked")

        try:
            search_path = (self.base_dir / path).resolve()
            if not search_path.exists():
                return ToolResult(error=f"Path not found: {path}")

            regex = re.compile(pattern)
            results = []

            if search_path.is_file():
                files = [search_path]
            else:
                files = list(search_path.rglob("*"))
                files = [f for f in files if f.is_file() and self.validator.check_path_traversal(str(f))]

            for f in files:
                if self.validator.is_blocked_extension(str(f)):
                    continue
                try:
                    for i, line in enumerate(f.read_text().splitlines(), 1):
                        if regex.search(line):
                            results.append(f"{f.relative_to(self.base_dir)}:{i}: {line}")
                            if len(results) >= 100:
                                break
                except Exception:
                    continue

            if not results:
                return ToolResult(content=f"No matches for '{pattern}'")

            return ToolResult(content="\n".join(results))
        except Exception as e:
            return ToolResult(error=str(e))
