import logging
import json
from unittest.mock import MagicMock, patch
from rich.console import Console
from io import StringIO
from src.agentframework.logging_utils import JsonFormatter, configure_logging
from src.agentframework.chat_render import make_clickable_links, strip_ansi, print_welcome, print_help

def test_json_formatter():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test message",
        args=(),
        exc_info=None
    )
    # Add extra attribute
    record.extra_attr = "extra_value"

    formatted = formatter.format(record)
    data = json.loads(formatted)

    assert data["level"] == "INFO"
    assert data["message"] == "Test message"
    assert data["extra_attr"] == "extra_value"

def test_configure_logging():
    with patch("logging.getLogger") as mock_get_logger:
        mock_root = MagicMock()
        mock_get_logger.return_value = mock_root

        # Test regular logging
        configure_logging(debug_enabled=True, debug_json=False)
        assert mock_root.setLevel.called
        assert mock_root.addHandler.called

        # Test JSON logging
        configure_logging(debug_enabled=True, debug_json=True)
        assert mock_root.addHandler.call_count == 2 # Second call

def test_make_clickable_links():
    text = "Check [Google](https://google.com) out."
    res = make_clickable_links(text)
    assert "\033]8;;https://google.com\007Google\033]8;;\007" in res

def test_strip_ansi():
    text = "\033[31mRed\033[0m Text"
    assert strip_ansi(text) == "Red Text"

def test_print_welcome():
    console = Console(file=StringIO(), force_terminal=False)
    print_welcome(console)
    output = console.file.getvalue()
    assert "Agent Framework" in output
    assert "Type 'help' for commands" in output

def test_print_help():
    console = Console(file=StringIO(), force_terminal=False)
    with patch("src.agentframework.chat_render.help_lines", return_value=["help - show help", "exit - quit"]):
        print_help(console)
        output = console.file.getvalue()
        assert "Commands:" in output
        assert "help - show help" in output
        assert "exit - quit" in output
