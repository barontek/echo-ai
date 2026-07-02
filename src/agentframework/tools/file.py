"""File tools for reading, writing, and listing files with safety."""

from pathlib import Path

from pydantic import BaseModel

from ..safety import SafetyConfig, SecurityValidator
from . import Tool, ToolResult


MAX_READ_SIZE = 50 * 1024 * 1024  # 50 MB


async def _async_read_text(path: Path, max_size: int = MAX_READ_SIZE) -> str:
    """Async file read with size limit to avoid TOCTOU and OOM."""
    try:
        import aiofiles

        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            return await f.read(max_size)
    except ImportError:
        return path.read_text(encoding="utf-8")[:max_size]


async def _async_write_text(path: Path, content: str) -> None:
    """Async file write to avoid blocking the event loop."""
    try:
        import aiofiles

        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(content)
    except ImportError:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


class ReadFileParams(BaseModel):
    """Parameters for ReadFileTool."""

    path: str


class WriteFileParams(BaseModel):
    """Parameters for WriteFileTool."""

    path: str
    content: str


class ListDirParams(BaseModel):
    """Parameters for ListDirTool."""

    path: str = "."


class FileSystemTool(Tool):
    """Base class for file system tools with workspace confinement."""

    def __init__(
        self,
        name: str,
        description: str,
        base_dir: str = ".",
        safety_config: SafetyConfig | None = None,
    ):
        super().__init__(name=name, description=description)
        self.base_dir = Path(base_dir).resolve()

        if safety_config:
            merged = SafetyConfig(
                **{k: v for k, v in safety_config.__dict__.items() if not k.startswith("_") and k != "workspace"},
                workspace=str(self.base_dir),
            )
            self.validator = SecurityValidator(merged)
        else:
            self.validator = SecurityValidator(
                SafetyConfig(workspace=str(self.base_dir))
            )

    def _resolve_path(self, path: str) -> Path:
        """Resolve a relative path against the base directory."""
        return (self.base_dir / path).resolve()


class ReadFileTool(FileSystemTool):
    """Read file contents with workspace confinement."""

    parameters_model = ReadFileParams

    def __init__(self, base_dir: str = ".", safety_config: SafetyConfig | None = None):
        super().__init__(
            name="read_file",
            description="Read the contents of a file from the filesystem.",
            base_dir=base_dir,
            safety_config=safety_config,
        )

    async def execute(self, path: str, **kwargs) -> ToolResult:
        """Read the file with safety checks."""
        if not self.validator.check_path_traversal(path):
            return ToolResult(error="Path traversal blocked")

        if self.validator.is_blocked_extension(path):
            return ToolResult(error="Cannot read file with blocked extension")

        if self.validator.is_blocked_path(path):
            return ToolResult(error="Cannot read blocked path")

        full_path = self._resolve_path(path)

        file_size_info = ""
        try:
            if full_path.exists() and full_path.is_file():
                size = full_path.stat().st_size
                file_size_info = f" ({size // 1024} KB)"
        except OSError:
            pass

        if self.validator.requires_approval("read_file", path=str(full_path)):
            approved = await self.validator.get_approval_async(
                "read_file", f"read: {path}{file_size_info}"
            )
            if not approved:
                return ToolResult(error="Read requires approval")

        try:
            if not full_path.exists():
                return ToolResult(error=f"File not found: {path}")
            if not full_path.is_file():
                return ToolResult(error=f"Not a file: {path}")

            if not self.validator.check_file_size(path=str(full_path)):
                return ToolResult(error="File too large")

            content = await _async_read_text(full_path)

            if not self.validator.check_file_size(content=content):
                return ToolResult(error="File content too large")

            return ToolResult(content=content)
        except Exception as e:
            return ToolResult(error=str(e))


class WriteFileTool(FileSystemTool):
    """Write file contents with workspace confinement."""

    parameters_model = WriteFileParams

    def __init__(self, base_dir: str = ".", safety_config: SafetyConfig | None = None):
        super().__init__(
            name="write_file",
            description="Create or overwrite a file with the given content.",
            base_dir=base_dir,
            safety_config=safety_config,
        )

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

        full_path = self._resolve_path(path)
        file_status = "new file"
        if full_path.exists():
            size = full_path.stat().st_size
            file_status = f"existing ({size} bytes)"

        if self.validator.requires_approval(
            "write_file", path=str(full_path), content=content
        ):
            approved = await self.validator.get_approval_async(
                "write_file", f"write: {path} - {file_status}"
            )
            if not approved:
                return ToolResult(error="Write requires approval")

        try:
            old_content = None
            if full_path.exists():
                max_backup_size = 10 * 1024 * 1024  # 10 MB
                if full_path.stat().st_size > max_backup_size:
                    return ToolResult(error=f"File too large to overwrite safely ({full_path.stat().st_size // 1024 // 1024} MB)")
                old_content = await _async_read_text(full_path)

            await _async_write_text(full_path, content)

            metadata = {
                "change": {
                    "action": "write",
                    "path": path,
                    "old_content": old_content,
                    "new_content": content,
                }
            }
            return ToolResult(content=f"Written to {path}", metadata=metadata)
        except Exception as e:
            return ToolResult(error=str(e))


class ListDirTool(FileSystemTool):
    """List directory contents with workspace confinement."""

    parameters_model = ListDirParams

    def __init__(self, base_dir: str = ".", safety_config: SafetyConfig | None = None):
        super().__init__(
            name="list_dir",
            description="List the contents of a directory.",
            base_dir=base_dir,
            safety_config=safety_config,
        )

    async def execute(self, path: str = ".", **kwargs) -> ToolResult:
        """List the directory with safety checks."""
        if not self.validator.check_path_traversal(path):
            return ToolResult(error="Path traversal blocked")

        try:
            full_path = self._resolve_path(path)
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
