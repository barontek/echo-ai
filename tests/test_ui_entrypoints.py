import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from src.agentframework.tui import TuiCallback, AgentDashboard

@pytest.fixture
def mock_agent():
    m = MagicMock()
    m.add_callback = MagicMock()
    return m

def test_tui_callback_methods():
    mock_app = MagicMock()
    callback = TuiCallback(mock_app)

    # Test on_run_start
    callback.on_run_start("run1", "test prompt")
    assert mock_app.call_from_thread.called

    # Test on_run_end
    callback.on_run_end("run1", "response")
    assert mock_app.call_from_thread.called

    # Test on_run_error
    callback.on_run_error("run1", Exception("error"))
    assert mock_app.call_from_thread.called

    # Test on_tool_start/end/error
    callback.on_tool_start("run1", "tool", {})
    callback.on_tool_end("run1", "tool", "res")
    callback.on_tool_error("run1", "tool", "err")
    assert mock_app.tools_panel.write_line.called or mock_app.call_from_thread.called

def test_agent_dashboard_init():
    mock_agent = MagicMock()
    app = AgentDashboard(mock_agent)
    assert app.agent == mock_agent
    assert mock_agent.add_callback.called

@pytest.mark.asyncio
async def test_agent_dashboard_full_flow():
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value="TUI Response")

    app = AgentDashboard(agent=mock_agent)
    # Mock call_from_thread to just execute the callback directly in tests
    app.call_from_thread = lambda func, *args, **kwargs: func(*args, **kwargs)

    # Use Textual's run_test to exercise the app logic
    async with app.run_test() as pilot:
        # Check initial state
        assert app.status_text == "Idle"
        assert app.title == "Echo AI Dashboard"

        # Simulate input
        await pilot.press("H", "e", "l", "l", "o", "enter")

        # The input_submitted handler should have cleared the input
        # and started a worker.
        # We need to wait for the worker to finish
        await pilot.pause()

        # Check logs
        # app.log_panel is a Log widget, we can check its lines if needed
        # but the main thing is it didn't crash and called agent.run
        mock_agent.run.assert_called_with("Hello")

def test_tui_callback_extended(mock_agent):
    app = MagicMock()
    callback = TuiCallback(app)

    callback.on_run_error("run-1", Exception("TUI Error"))
    assert app.call_from_thread.called

    callback.on_tool_start("run-1", "test_tool", {"arg": 1})
    callback.on_tool_end("run-1", "test_tool", "result")
    callback.on_tool_error("run-1", "test_tool", "error")
    assert app.call_from_thread.call_count > 0

@patch("src.agentframework.tui.AgentDashboard.run")
@patch("src.agentframework.tui.create_agent")
def test_dashboard_run_entrypoint(mock_create_agent, mock_run):
    from src.agentframework.tui import run_dashboard
    run_dashboard()
    assert mock_create_agent.called
    assert mock_run.called

def test_agent_dashboard_initial_state():
    mock_agent = MagicMock()
    app = AgentDashboard(mock_agent)
    # Check reactive attribute
    assert app.status_text == "Initializing..."
    app.update_status("Test")
    assert app.status_text == "Test"
