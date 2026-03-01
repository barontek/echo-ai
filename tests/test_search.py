"""Tests for search tools (glob and grep)."""

import pytest
import tempfile
from pathlib import Path
import asyncio

from src.agentframework.tools.search import GlobTool, GrepTool
from src.agentframework.safety import SafetyConfig


class TestGlobTool:
    """Tests for GlobTool."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def setup_files(self, temp_dir):
        (Path(temp_dir) / "file1.py").write_text("print('hello')")
        (Path(temp_dir) / "file2.txt").write_text("hello world")
        (Path(temp_dir) / "subdir").mkdir()
        (Path(temp_dir) / "subdir" / "module.py").write_text("def foo(): pass")
        (Path(temp_dir) / "subdir" / "data.json").write_text('{"key": "value"}')
        (Path(temp_dir) / ".env").write_text("SECRET=123")
        return temp_dir

    @pytest.fixture
    def tool(self, temp_dir):
        config = SafetyConfig(workspace=temp_dir)
        return GlobTool(base_dir=temp_dir, safety_config=config)

    def test_tool_initialization(self, temp_dir):
        tool = GlobTool(base_dir=temp_dir)
        assert tool.name == "glob"
        assert tool.base_dir == Path(temp_dir).resolve()

    def test_tool_schema(self, temp_dir):
        tool = GlobTool(base_dir=temp_dir)
        schema = tool.schema
        assert schema["function"]["name"] == "glob"
        assert "pattern" in schema["function"]["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_glob_all_py_files(self, tool, setup_files):
        result = await tool.execute(pattern="**/*.py")
        assert result.error is None
        assert "file1.py" in result.content
        assert "module.py" in result.content

    @pytest.mark.asyncio
    async def test_glob_txt_files(self, tool, setup_files):
        result = await tool.execute(pattern="*.txt")
        assert result.error is None
        assert "file2.txt" in result.content

    @pytest.mark.asyncio
    async def test_glob_no_matches(self, tool, setup_files):
        result = await tool.execute(pattern="**/*.nonexistent")
        assert result.error is None
        assert "No files matching" in result.content

    @pytest.mark.asyncio
    async def test_glob_nested(self, tool, setup_files):
        result = await tool.execute(pattern="**/*")
        assert result.error is None
        assert "file1.py" in result.content

    @pytest.mark.asyncio
    async def test_glob_blocked_extension(self, tool, setup_files):
        result = await tool.execute(pattern="**/*.env")
        assert result.error is not None
        assert "blocked" in result.error.lower()


class TestGrepTool:
    """Tests for GrepTool."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def setup_files(self, temp_dir):
        (Path(temp_dir) / "file1.py").write_text("def hello():\n    print('hello world')")
        (Path(temp_dir) / "file2.txt").write_text("hello from txt\nanother line")
        (Path(temp_dir) / "subdir").mkdir()
        (Path(temp_dir) / "subdir" / "module.py").write_text("def foo():\n    return 'bar'")
        (Path(temp_dir) / ".secret").write_text("password=secret123")
        return temp_dir

    @pytest.fixture
    def tool(self, temp_dir):
        config = SafetyConfig(workspace=temp_dir)
        return GrepTool(base_dir=temp_dir, safety_config=config)

    def test_tool_initialization(self, temp_dir):
        tool = GrepTool(base_dir=temp_dir)
        assert tool.name == "grep"
        assert tool.base_dir == Path(temp_dir).resolve()

    def test_tool_schema(self, temp_dir):
        tool = GrepTool(base_dir=temp_dir)
        schema = tool.schema
        assert schema["function"]["name"] == "grep"
        assert "pattern" in schema["function"]["parameters"]["properties"]
        assert "path" in schema["function"]["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_grep_simple_pattern(self, tool, setup_files):
        result = await tool.execute(pattern="hello")
        assert result.error is None
        assert "file1.py" in result.content or "file2.txt" in result.content

    @pytest.mark.asyncio
    async def test_grep_in_specific_file(self, tool, setup_files):
        result = await tool.execute(pattern="hello", path="file1.py")
        assert result.error is None
        assert "file1.py" in result.content

    @pytest.mark.asyncio
    async def test_grep_no_matches(self, tool, setup_files):
        result = await tool.execute(pattern="nonexistent_xyz_pattern")
        assert result.error is None
        assert "No matches" in result.content

    @pytest.mark.asyncio
    async def test_grep_blocked_file(self, tool, setup_files):
        result = await tool.execute(pattern=".", path=".")
        assert ".secret" not in result.content

    @pytest.mark.asyncio
    async def test_grep_with_regex(self, tool, setup_files):
        result = await tool.execute(pattern="def .*\\(\\)")
        assert result.error is None

    @pytest.mark.asyncio
    async def test_grep_path_traversal_blocked(self, tool, setup_files):
        result = await tool.execute(pattern=".", path="../etc")
        assert result.error is not None
        assert "traversal" in result.error.lower()

    @pytest.mark.asyncio
    async def test_grep_nonexistent_path(self, tool, setup_files):
        result = await tool.execute(pattern=".", path="nonexistent_dir")
        assert result.error is not None
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_grep_subdirectory(self, tool, setup_files):
        result = await tool.execute(pattern="bar", path=".")
        assert result.error is None
        assert "module.py" in result.content


class TestGrepToolEdgeCases:
    """Edge case tests for GrepTool."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def tool(self, temp_dir):
        config = SafetyConfig(workspace=temp_dir)
        return GrepTool(base_dir=temp_dir, safety_config=config)

    @pytest.mark.asyncio
    async def test_grep_empty_pattern(self, tool, temp_dir):
        (Path(temp_dir) / "test.txt").write_text("some content")
        result = await tool.execute(pattern="")
        assert result.error is None or result.content is not None

    @pytest.mark.asyncio
    async def test_grep_many_matches(self, tool, temp_dir):
        content = "\n".join([f"line {i}" for i in range(200)])
        (Path(temp_dir) / "many.txt").write_text(content)
        result = await tool.execute(pattern="line", path="many.txt")
        assert result.error is None
