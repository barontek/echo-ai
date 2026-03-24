"""Dependency injection for the Echo AI API."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent import Agent


@dataclass
class AgentRegistry:
    """Registry for managing agent instances.

    Replaces the global `agents` dict with a proper dependency-injectable
    container for better testability and multi-instance support.
    """

    agents: dict[str, "Agent"] = field(default_factory=dict)

    def get(self, key: str) -> "Agent | None":
        """Get an agent by key."""
        return self.agents.get(key)

    def set(self, key: str, agent: "Agent") -> None:
        """Set an agent by key."""
        self.agents[key] = agent

    def has(self, key: str) -> bool:
        """Check if an agent exists."""
        return key in self.agents

    def clear(self) -> None:
        """Clear all agents (useful for testing)."""
        self.agents.clear()


_registry = AgentRegistry()


def get_agent_registry() -> AgentRegistry:
    """Get the global agent registry instance.

    This can be overridden in tests by monkey-patching or using
    FastAPI's dependency override system.
    """
    return _registry
