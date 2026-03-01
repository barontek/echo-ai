"""File tools for reading, writing, and listing files with safety."""

from pathlib import Path
from typing import Any

from ..safety import SafetyConfig, SecurityValidator
from . import Tool, ToolResult


class ReadFileTool(Tool):
    """Read file contents with workspace confinement."""

    def __init__(self, base_dir: str = ".", safety_config: SafetyConfig | None = None):
        super().__init__(
            name="read_file",
            description="Read the contents of a file from the filesystem.",
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
                "path": {
                    "type": "string",
                    "description": "The path to the file to read",
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs) -> ToolResult:
        """Read the file with safety checks."""
        if not self.validator.check_path_traversal(path):
            return ToolResult(error="Path traversal blocked")

        if self.validator.is_blocked_extension(path):
            return ToolResult(error="Cannot read file with blocked extension")

        if self.validator.is_blocked_path(path):
            return ToolResult(error="Cannot read blocked path")

        full_path = (self.base_dir / path).resolve()
        
        file_size_info = ""
        try:
            if full_path.exists() and full_path.is_file():
                size = full_path.stat().st_size
                file_size_info = f" ({size // 1024} KB)"
        except Exception:
            pass

        if self.validator.requires_approval("read_file", path=str(full_path)):
            approved = self.validator.get_approval("read_file", f"read: {path}{file_size_info}")
            if not approved:
                return ToolResult(error="Read requires approval")

        try:
            if not full_path.exists():
                return ToolResult(error=f"File not found: {path}")
            if not full_path.is_file():
                return ToolResult(error=f"Not a file: {path}")

            if not self.validator.check_file_size(path=str(full_path)):
                return ToolResult(error="File too large")

            content = full_path.read_text()

            if not self.validator.check_file_size(content=content):
                return ToolResult(error="File content too large")

            return ToolResult(content=content)
        except Exception as e:
            return ToolResult(error=str(e))


class WriteFileTool(Tool):
    """Write file contents with workspace confinement."""

    def __init__(self, base_dir: str = ".", safety_config: SafetyConfig | None = None):
        super().__init__(
            name="write_file",
            description="Create or overwrite a file with the given content.",
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
                "path": {
                    "type": "string",
                    "description": "The path to the file to write",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str, **kwargs) -> ToolResult:
        """Write the file with safety checks."""
        if not self.validator.check_path_traversal(path):
            return ToolResult(error="Path traversal blocked")

        if self.validator.is_blocked_extension(path):
            return ToolResult(error="Cannot write file with blocked extension")

        if self.validator.is_blocked_path(path):
            return ToolResult(error="Cannot write to blocked path")

        if not self.validator.check_file_size(content=content):
            return ToolResult(error="Content too large")

        full_path = (self.base_dir / path).resolve()
        file_status = "new file"
        if full_path.exists():
            size = full_path.stat().st_size
            file_status = f"existing ({size} bytes)"

        if self.validator.requires_approval("write_file", path=str(full_path), content=content):
            approved = self.validator.get_approval("write_file", f"write: {path} - {file_status}")
            if not approved:
                return ToolResult(error="Write requires approval")

        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
            return ToolResult(content=f"Written to {path}")
        except Exception as e:
            return ToolResult(error=str(e))


class ListDirTool(Tool):
    """List directory contents with workspace confinement."""

    def __init__(self, base_dir: str = ".", safety_config: SafetyConfig | None = None):
        super().__init__(
            name="list_dir",
            description="List the contents of a directory.",
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
                "path": {
                    "type": "string",
                    "description": "The path to list, relative to the workspace (e.g., 'src' or '.')",
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str = ".", **kwargs) -> ToolResult:
        """List the directory with safety checks."""
        if not self.validator.check_path_traversal(path):
            return ToolResult(error="Path traversal blocked")

        try:
            full_path = (self.base_dir / path).resolve()
            if not full_path.exists():
                return ToolResult(error=f"Directory not found: {path}")
            if not full_path.is_dir():
                return ToolResult(error=f"Not a directory: {path}")
            items = list(full_path.iterdir())
            result = "\n".join(
                f"{item.name}/" if item.is_dir() else item.name
                for item in sorted(items)
            )
            return ToolResult(content=result)
        except Exception as e:
            return ToolResult(error=str(e))
