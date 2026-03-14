import asyncio

import pytest
from src.agentframework.tools.file import ReadFileTool, WriteFileTool, ListDirTool
from src.agentframework.safety import SafetyConfig


# Helper to run async in non-async test
def asyncio_run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def temp_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace

@pytest.fixture
def config(temp_workspace):
    return SafetyConfig(workspace=str(temp_workspace))

def test_read_file_blocked_extension(temp_workspace, config):
    tool = ReadFileTool(base_dir=str(temp_workspace), safety_config=config)

    blocked_file = temp_workspace / "test.key"
    blocked_file.write_text("content")

    result = asyncio_run(tool.execute(path="test.key"))
    assert result.error == "Cannot read file with blocked extension"

def test_read_file_approval_required(temp_workspace, config, monkeypatch):
    config.read_requires_approval = True
    tool = ReadFileTool(base_dir=str(temp_workspace), safety_config=config)

    test_file = temp_workspace / "test.txt"
    test_file.write_text("content")

    config.approval_callback = lambda tool, details: False

    result = asyncio_run(tool.execute(path="test.txt"))
    assert result.error == "Read requires approval"

def test_write_file_metadata(temp_workspace, config):
    config.approval_callback = lambda tool, details: True
    tool = WriteFileTool(base_dir=str(temp_workspace), safety_config=config)

    result = asyncio_run(tool.execute(path="new_metadata.txt", content="hello"))
    assert result.metadata is not None
    assert result.metadata["change"]["action"] == "write"
    assert result.metadata["change"]["old_content"] is None
    assert result.metadata["change"]["new_content"] == "hello"

    result = asyncio_run(tool.execute(path="new_metadata.txt", content="world"))
    assert result.metadata["change"]["old_content"] == "hello"
    assert result.metadata["change"]["new_content"] == "world"

def test_list_dir_not_a_directory(temp_workspace, config):
    tool = ListDirTool(base_dir=str(temp_workspace), safety_config=config)

    file_path = temp_workspace / "not_a_dir.txt"
    file_path.write_text("content")

    result = asyncio_run(tool.execute(path="not_a_dir.txt"))
    assert "Not a directory" in result.error
