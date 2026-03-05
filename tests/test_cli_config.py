"""Tests for CLI configuration defaults."""

from src.agentframework.cli import get_safety_config
from src.agentframework.chat import get_safety_config as get_chat_safety_config


def test_cli_safety_defaults_require_approval_when_missing_key():
    config = {"safety": {}, "tools": {}}
    safety = get_safety_config(config)
    assert "bash" in safety.require_approval_for
    assert "write_file" in safety.require_approval_for


def test_cli_safety_uses_explicit_approval_list_when_present():
    config = {"safety": {"require_approval_for": ["read_file"]}, "tools": {}}
    safety = get_safety_config(config)
    assert safety.require_approval_for == ["read_file"]


def test_chat_safety_defaults_require_approval_when_missing_key():
    config = {"safety": {}, "tools": {}}
    safety = get_chat_safety_config(config)
    assert "bash" in safety.require_approval_for
    assert "write_file" in safety.require_approval_for
