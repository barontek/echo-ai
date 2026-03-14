"""Tests for CLI commands and interactive mode.

Merged from test_cli_extended.py and test_cli_runtime_extended.py.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from src.agentframework.chat_commands import normalize_command, execute_command
from src.agentframework.cli import run_single, interactive_mode


# ---------------------------------------------------------------------------
# Chat commands
# ---------------------------------------------------------------------------

def test_normalize_command():
    assert normalize_command("/quit") == "/exit"
    assert normalize_command("/sessions") == "/chats"
    assert normalize_command("/unknown") == "/unknown"
    assert normalize_command("/help") == "/help"

def test_execute_exit_command():
    agent = MagicMock()
    console = MagicMock()
    result = execute_command("/exit", "", agent, console)
    assert result is False
    assert agent.save_session.called

def test_execute_new_command():
    agent = MagicMock()
    console = MagicMock()
    result = execute_command("/new", "", agent, console)
    assert result is True
    assert agent.save_session.called
    assert len(agent.messages) == 0
    assert console.clear.called

def test_execute_save_command():
    agent = MagicMock()
    console = MagicMock()
    execute_command("/save", " my_chat ", agent, console)
    agent.save_session.assert_called_with("my_chat")

def test_execute_load_command():
    agent = MagicMock()
    console = MagicMock()
    execute_command("/load", " chat1 ", agent, console)
    agent.load_session.assert_called_with("chat1")

def test_execute_load_command_usage():
    agent = MagicMock()
    console = MagicMock()
    execute_command("/load", "  ", agent, console)
    assert "Usage" in console.print.call_args[0][0]

def test_execute_chats_command():
    agent = MagicMock()
    agent.list_sessions.return_value = ["s1", "s2"]
    console = MagicMock()
    execute_command("/chats", "", agent, console)
    assert console.print.called
    printed = [args[0][0] for args in console.print.call_args_list]
    assert any("s1" in p for p in printed)

def test_execute_undo_redo():
    agent = MagicMock()
    console = MagicMock()
    execute_command("/undo", "", agent, console)
    assert agent.undo.called
    execute_command("/redo", "", agent, console)
    assert agent.redo.called

def test_execute_model_switch():
    agent = MagicMock()
    agent.config.provider = "openai"
    console = MagicMock()
    with patch("src.agentframework.providers.get_provider") as mock_get:
        execute_command("/model", " gpt-4 ", agent, console)
        assert agent.config.model == "gpt-4"
        assert mock_get.called

def test_execute_temperature_switch():
    agent = MagicMock()
    console = MagicMock()
    execute_command("/temperature", " 0.8 ", agent, console)
    assert agent.config.temperature == 0.8

def test_execute_temperature_invalid():
    agent = MagicMock()
    console = MagicMock()
    execute_command("/temperature", " 2.5 ", agent, console)
    assert "Invalid" in console.print.call_args[0][0]

@pytest.mark.asyncio
async def test_run_single():
    agent = MagicMock()
    agent.run_streaming = AsyncMock()
    with patch("sys.stdout.write") as mock_write:
        await run_single(agent, "test task")
        agent.run_streaming.assert_called()
        assert mock_write.called


# ---------------------------------------------------------------------------
# Interactive mode & runtime (from test_cli_runtime_extended.py)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_interactive_mode_exit():
    agent = MagicMock()
    with patch("src.agentframework.cli.console.input", return_value="/exit"), \
         patch("src.agentframework.cli.console.print") as mock_print:
        await interactive_mode(agent)
        assert agent.save_session.called
        assert any("Goodbye" in str(args) for args in mock_print.call_args_list)

@pytest.mark.asyncio
async def test_interactive_mode_commands():
    agent = MagicMock()
    inputs = ["/help", "", "/exit"]
    with patch("src.agentframework.cli.console.input", side_effect=inputs), \
         patch("src.agentframework.cli.console.print") as mock_print:
        await interactive_mode(agent)
        assert any("Commands:" in str(args) for args in mock_print.call_args_list)

@pytest.mark.asyncio
async def test_interactive_mode_run_streaming():
    agent = MagicMock()
    agent.run_streaming = AsyncMock()
    inputs = ["hello", "/exit"]
    with patch("src.agentframework.cli.console.input", side_effect=inputs), \
         patch("src.agentframework.cli.sys.stdout.write") as mock_write:
        await interactive_mode(agent)
        agent.run_streaming.assert_called_once()
        assert mock_write.called

@pytest.mark.asyncio
async def test_interactive_mode_keyboard_interrupt():
    agent = MagicMock()
    with patch("src.agentframework.cli.console.input", side_effect=KeyboardInterrupt):
        await interactive_mode(agent)
        assert agent.save_session.called

@pytest.mark.asyncio
async def test_run_single_thinking_markers():
    agent = MagicMock()

    async def mock_run_streaming(task, on_chunk):
        on_chunk("__THINKING__")
        on_chunk("thoughts")
        on_chunk("__THINKING_END__")
        on_chunk("actual response")
        return "full"

    agent.run_streaming = AsyncMock(side_effect=mock_run_streaming)

    with patch("sys.stdout.write") as mock_write:
        await run_single(agent, "test task")
        calls = [args[0][0] for args in mock_write.call_args_list]
        assert any("\033[90mthoughts\033[0m" in c for c in calls)
        assert any("actual response" in c for c in calls)
