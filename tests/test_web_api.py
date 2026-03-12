"""Tests for web API agent bootstrapping."""

from types import SimpleNamespace

from src.agentframework import web_api


def test_create_runtime_agent_uses_configured_tools(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        web_api,
        "load_config",
        lambda: {
            "model": {"temperature": 0.6, "base_url": "http://localhost:9999"},
            "agent": {
                "max_iterations": 7,
                "system_prompt": "Custom prompt",
                "session_enabled": False,
                "session_dir": ".sessions-test",
            },
        },
    )

    fake_safety = SimpleNamespace(workspace="/tmp/workspace")
    monkeypatch.setattr(web_api, "get_safety_config", lambda cfg: fake_safety)

    fake_tools = [SimpleNamespace(name="bash")]
    monkeypatch.setattr(web_api, "get_tools", lambda cfg, safety: fake_tools)

    def fake_create_agent(agent_config, api_key=None):
        captured["agent_config"] = agent_config
        captured["api_key"] = api_key
        return SimpleNamespace(config=agent_config)

    monkeypatch.setattr(web_api, "create_agent", fake_create_agent)

    result = web_api._create_runtime_agent("ollama", "qwen3:4b-instruct", api_key="k")

    assert result.config.tools == fake_tools
    assert result.config.temperature == 0.6
    assert result.config.base_url == "http://localhost:9999"
    assert result.config.max_iterations == 7
    assert result.config.session_enabled is False
    assert result.config.session_dir == ".sessions-test"
    assert "Custom prompt" in result.config.system_prompt
    assert "Workspace (file operations confined to): /tmp/workspace" in result.config.system_prompt
    assert captured["api_key"] == "k"


def test_create_runtime_agent_sets_default_system_prompt(monkeypatch):
    monkeypatch.setattr(web_api, "load_config", lambda: {})
    monkeypatch.setattr(web_api, "get_safety_config", lambda cfg: SimpleNamespace(workspace="."))
    monkeypatch.setattr(web_api, "get_tools", lambda cfg, safety: [])
    monkeypatch.setattr(
        web_api,
        "create_agent",
        lambda agent_config, api_key=None: SimpleNamespace(config=agent_config),
    )

    result = web_api._create_runtime_agent("ollama", "qwen3:4b-instruct")

    assert result.config.tools == []
    assert "You are an AI assistant with access to various tools." in result.config.system_prompt
