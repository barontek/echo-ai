"""Entry-point consistency checks for shared config bootstrap."""

from src.agentframework.chat import get_safety_config as get_chat_safety_config
from src.agentframework.chat import get_tools as get_chat_tools
from src.agentframework.cli import get_safety_config as get_cli_safety_config
from src.agentframework.cli import get_tools as get_cli_tools


def test_cli_and_chat_safety_defaults_are_identical():
    config = {"safety": {}, "tools": {}}
    cli_safety = get_cli_safety_config(config)
    chat_safety = get_chat_safety_config(config)

    assert cli_safety.require_approval_for == chat_safety.require_approval_for
    assert "bash" in cli_safety.require_approval_for
    assert "write_file" in cli_safety.require_approval_for


def test_cli_and_chat_tool_bootstrap_are_identical_names():
    config = {
        "tools": {
            "enabled": ["read_file", "list_dir", "glob", "memory"],
        },
        "safety": {},
    }

    cli_safety = get_cli_safety_config(config)
    chat_safety = get_chat_safety_config(config)

    cli_tools = get_cli_tools(config, cli_safety)
    chat_tools = get_chat_tools(config, chat_safety)

    assert [t.name for t in cli_tools] == [t.name for t in chat_tools]
