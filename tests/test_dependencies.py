"""Tests for dependency injection."""

from unittest.mock import MagicMock
from src.agentframework.dependencies import AgentRegistry, get_agent_registry


class TestAgentRegistry:
    def test_initial_state(self):
        registry = AgentRegistry()
        assert registry.agents == {}

    def test_set_and_get(self):
        registry = AgentRegistry()
        agent = MagicMock()
        registry.set("agent1", agent)
        assert registry.get("agent1") is agent

    def test_get_nonexistent(self):
        registry = AgentRegistry()
        assert registry.get("nonexistent") is None

    def test_has_existing(self):
        registry = AgentRegistry()
        registry.set("agent1", MagicMock())
        assert registry.has("agent1") is True

    def test_has_nonexistent(self):
        registry = AgentRegistry()
        assert registry.has("nonexistent") is False

    def test_clear(self):
        registry = AgentRegistry()
        registry.set("a", MagicMock())
        registry.set("b", MagicMock())
        registry.clear()
        assert registry.agents == {}
        assert registry.get("a") is None

    def test_overwrite_existing(self):
        registry = AgentRegistry()
        agent1 = MagicMock()
        agent2 = MagicMock()
        registry.set("agent1", agent1)
        registry.set("agent1", agent2)
        assert registry.get("agent1") is agent2

    def test_multiple_agents(self):
        registry = AgentRegistry()
        agents = {"a": MagicMock(), "b": MagicMock(), "c": MagicMock()}
        for key, agent in agents.items():
            registry.set(key, agent)
        assert len(registry.agents) == 3
        for key, agent in agents.items():
            assert registry.get(key) is agent


class TestGetAgentRegistry:
    def test_returns_singleton(self):
        reg1 = get_agent_registry()
        reg2 = get_agent_registry()
        assert reg1 is reg2

    def test_is_agent_registry_instance(self):
        registry = get_agent_registry()
        assert isinstance(registry, AgentRegistry)

    def test_can_use_in_tests(self):
        registry = get_agent_registry()
        registry.clear()
        agent = MagicMock()
        registry.set("test_agent", agent)
        assert registry.get("test_agent") is agent
        registry.clear()
