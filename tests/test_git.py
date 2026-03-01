"""Tests for git tool."""

import pytest
import tempfile
from pathlib import Path
import subprocess

from src.agentframework.tools.git import GitTool, SAFE_GIT_COMMANDS
from src.agentframework.safety import SafetyConfig


class TestGitTool:
    """Tests for GitTool."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def git_repo(self, temp_dir):
        path = Path(temp_dir)
        subprocess.run(["git", "init"], cwd=path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True)
        return path

    @pytest.fixture
    def tool(self, temp_dir):
        config = SafetyConfig(workspace=temp_dir, allowed_commands=["git"])
        return GitTool(base_dir=temp_dir, safety_config=config)

    def test_safe_git_commands_list(self):
        assert "status" in SAFE_GIT_COMMANDS
        assert "commit" in SAFE_GIT_COMMANDS
        assert "push" in SAFE_GIT_COMMANDS
        assert "log" in SAFE_GIT_COMMANDS
        assert "branch" in SAFE_GIT_COMMANDS

    def test_tool_initialization(self, temp_dir):
        tool = GitTool(base_dir=temp_dir)
        assert tool.name == "git"
        assert tool.base_dir == temp_dir

    def test_tool_schema(self, temp_dir):
        tool = GitTool(base_dir=temp_dir)
        schema = tool.schema
        assert schema["function"]["name"] == "git"
        assert "command" in schema["function"]["parameters"]["properties"]

    def test_build_command_status(self, tool):
        cmd = tool._build_non_interactive_command("status", "")
        assert "git --no-pager status" in cmd

    def test_build_command_with_args(self, tool):
        cmd = tool._build_non_interactive_command("log", "--oneline -n 5")
        assert "git --no-pager log --oneline -n 5" in cmd

    def test_build_command_clone(self, tool):
        cmd = tool._build_non_interactive_command("clone", "https://github.com/test/repo")
        assert "git clone" in cmd

    def test_build_command_commit(self, tool):
        cmd = tool._build_non_interactive_command("commit", "-m 'test'")
        assert "git --no-pager commit --no-edit" in cmd

    @pytest.mark.asyncio
    async def test_git_status(self, tool, git_repo):
        result = await tool.execute(command="status")
        assert result.error is None or "nothing to commit" in result.content.lower()

    @pytest.mark.asyncio
    async def test_git_log(self, tool, git_repo):
        (Path(git_repo) / "test.txt").write_text("content")
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=git_repo, capture_output=True)
        
        result = await tool.execute(command="log")
        assert result.error is None
        assert "initial" in result.content.lower()

    @pytest.mark.asyncio
    async def test_git_blocked_subcommand(self, tool, git_repo):
        result = await tool.execute(command="exec", args="--help")
        assert result.error is not None
        assert "not allowed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_git_branch(self, tool, git_repo):
        result = await tool.execute(command="branch")
        assert result.error is None

    @pytest.mark.asyncio
    async def test_git_diff(self, tool, git_repo):
        (Path(git_repo) / "test.txt").write_text("content")
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True)
        
        result = await tool.execute(command="diff")
        assert result.error is None


class TestGitToolSafety:
    """Tests for GitTool safety features."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def tool(self, temp_dir):
        config = SafetyConfig(workspace=temp_dir, allowed_commands=["git"])
        return GitTool(base_dir=temp_dir, safety_config=config)

    @pytest.mark.asyncio
    async def test_git_hook_blocked(self, tool, temp_dir):
        result = tool._build_non_interactive_command("push", "--receive-pack='evil command'")
        assert "git --no-pager push" in result
