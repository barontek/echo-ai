"""Tests for tool system."""

import pytest
from pathlib import Path
import tempfile

from src.agentframework.tools import Tool, ToolResult
from src.agentframework.tools.file import ReadFileTool, WriteFileTool, ListDirTool
from src.agentframework.safety import SafetyConfig


class TestToolResult:
    """Tests for ToolResult dataclass."""

    def test_tool_result_content(self):
        result = ToolResult(content="Hello world")
        assert result.content == "Hello world"
        assert result.error is None
        assert str(result) == "Hello world"

    def test_tool_result_error(self):
        result = ToolResult(error="Something went wrong")
        assert result.content == ""
        assert result.error == "Something went wrong"
        assert "Error: Something went wrong" in str(result)


class MockTool(Tool):
    """A mock tool for testing."""

    def __init__(self, name: str = "mock", description: str = "A mock tool"):
        super().__init__(name, description)
        self.executed = False

    def _get_parameters(self):
        return {
            "type": "object",
            "properties": {
                "arg1": {"type": "string", "description": "First argument"},
            },
            "required": ["arg1"],
        }

    async def execute(self, arg1: str, **kwargs):
        self.executed = True
        return ToolResult(content=f"Executed with {arg1}")


class TestTool:
    """Tests for Tool base class."""

    def test_tool_initialization(self):
        tool = MockTool("test", "A test tool")
        assert tool.name == "test"
        assert tool.description == "A test tool"

    def test_tool_schema(self):
        tool = MockTool("test", "A test tool")
        schema = tool.schema

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "test"
        assert schema["function"]["description"] == "A test tool"
        assert "parameters" in schema["function"]

    @pytest.mark.asyncio
    async def test_tool_execute(self):
        tool = MockTool()
        result = await tool.execute(arg1="test-value")

        assert tool.executed is True
        assert result.content == "Executed with test-value"


class TestReadFileTool:
    """Tests for ReadFileTool."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def tool(self, temp_dir):
        config = SafetyConfig(workspace=temp_dir)
        return ReadFileTool(base_dir=temp_dir, safety_config=config)

    @pytest.fixture
    def test_file(self, temp_dir):
        path = Path(temp_dir) / "test.txt"
        path.write_text("Hello, World!")
        return path

    @pytest.mark.asyncio
    async def test_read_file(self, tool, test_file):
        result = await tool.execute(path="test.txt")
        assert result.error is None
        assert "Hello, World!" in result.content

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, tool):
        result = await tool.execute(path="does_not_exist.txt")
        assert result.error is not None
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_with_traversal_attempt(self, tool):
        result = await tool.execute(path="../etc/passwd")
        assert result.error is not None
        assert "traversal" in result.error.lower()


class TestWriteFileTool:
    """Tests for WriteFileTool."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def tool(self, temp_dir):
        config = SafetyConfig(
            workspace=temp_dir,
            require_approval_for=[],
        )
        return WriteFileTool(base_dir=temp_dir, safety_config=config)

    @pytest.mark.asyncio
    async def test_write_new_file(self, tool, temp_dir):
        result = await tool.execute(path="new_file.txt", content="New content")
        assert result.error is None

        content = (Path(temp_dir) / "new_file.txt").read_text()
        assert content == "New content"

    @pytest.mark.asyncio
    async def test_overwrite_existing_file(self, tool, temp_dir):
        path = Path(temp_dir) / "existing.txt"
        path.write_text("Original")

        result = await tool.execute(path="existing.txt", content="Updated")
        assert result.error is None

        assert path.read_text() == "Updated"

    @pytest.mark.asyncio
    async def test_write_with_traversal(self, tool):
        result = await tool.execute(path="../outside.txt", content="test")
        assert result.error is not None
        assert "traversal" in result.error.lower()

    @pytest.mark.asyncio
    async def test_write_to_subdirectory(self, tool, temp_dir):
        result = await tool.execute(
            path="subdir/nested/file.txt",
            content="Nested content"
        )
        assert result.error is None

        content = (Path(temp_dir) / "subdir/nested/file.txt").read_text()
        assert content == "Nested content"


class TestListDirTool:
    """Tests for ListDirTool."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def tool(self, temp_dir):
        config = SafetyConfig(workspace=temp_dir)
        return ListDirTool(base_dir=temp_dir, safety_config=config)

    @pytest.fixture
    def setup_files(self, temp_dir):
        (Path(temp_dir) / "file1.txt").write_text("a")
        (Path(temp_dir) / "file2.txt").write_text("b")
        (Path(temp_dir) / "subdir").mkdir()
        (Path(temp_dir) / "subdir" / "file3.txt").write_text("c")

    @pytest.mark.asyncio
    async def test_list_directory(self, tool, setup_files):
        result = await tool.execute(path=".")
        assert result.error is None
        assert "file1.txt" in result.content
        assert "file2.txt" in result.content
        assert "subdir" in result.content

    @pytest.mark.asyncio
    async def test_list_nonexistent_directory(self, tool):
        result = await tool.execute(path="nonexistent")
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_list_with_traversal(self, tool):
        result = await tool.execute(path="../etc")
        assert result.error is not None
        assert "traversal" in result.error.lower()
