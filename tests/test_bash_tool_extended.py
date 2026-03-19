import pytest
import asyncio
import signal
from unittest.mock import MagicMock, patch, AsyncMock
from src.agentframework.tools.bash import BashTool
from src.agentframework.safety import SafetyConfig


def test_bash_tool_init():
    safety = SafetyConfig(max_execution_time=30)
    tool = BashTool(timeout=60, safety_config=safety)
    assert tool.timeout == 30  # Clipped to safety max


def test_bash_tool_blocked_command():
    safety = SafetyConfig(blocked_commands=["rm"])
    tool = BashTool(safety_config=safety)

    # Run in async context
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(tool.execute("rm -rf /"))
    assert result.error is not None and "blocked" in result.error.lower()


@pytest.mark.asyncio
async def test_bash_tool_approval_denied():
    mock_callback = MagicMock(return_value=False)
    safety = SafetyConfig(
        require_approval_for=["bash"], approval_callback=mock_callback
    )
    tool = BashTool(safety_config=safety)

    result = await tool.execute("ls")
    assert result.error == "Command requires approval"
    assert mock_callback.called


@pytest.fixture
def loose_safety():
    return SafetyConfig(require_approval_for=[])


@pytest.mark.asyncio
async def test_bash_tool_execution_success(loose_safety):
    tool = BashTool(safety_config=loose_safety)

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"hello\nworld", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
        result = await tool.execute("echo 'hello world'")
        assert result.content == "hello\nworld"


@pytest.mark.asyncio
async def test_bash_tool_execution_error(loose_safety):
    tool = BashTool(safety_config=loose_safety)

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"some output", b"error message"))
    mock_proc.returncode = 1

    with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
        result = await tool.execute("false")
        assert "some output" in result.content
        assert "error message" in result.content


@pytest.mark.asyncio
async def test_bash_tool_timeout(loose_safety):
    tool = BashTool(timeout=1, safety_config=loose_safety)

    with patch("asyncio.create_subprocess_shell") as mock_create:
        mock_proc = MagicMock()
        mock_proc.pid = 123
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_proc.wait = AsyncMock()
        mock_create.return_value = mock_proc

        with patch("os.killpg") as mock_killpg, patch("os.getpgid", return_value=456):
            result = await tool.execute("sleep 10")
            assert result.error is not None and "timed out" in result.error
            assert mock_killpg.called
            mock_killpg.assert_called_with(456, signal.SIGKILL)


@pytest.mark.asyncio
async def test_bash_tool_output_truncation(loose_safety):
    tool = BashTool(safety_config=loose_safety)

    large_output = b"a" * 100005
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(large_output, b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
        result = await tool.execute("echo large")
        assert len(result.content) > 100000
        assert "WARNING: Output heavily truncated" in result.content


@pytest.mark.asyncio
async def test_bash_tool_exception(loose_safety):
    tool = BashTool(safety_config=loose_safety)
    with patch(
        "asyncio.create_subprocess_shell", side_effect=RuntimeError("Subprocess failed")
    ):
        result = await tool.execute("ls")
        assert result.error == "Subprocess failed"
