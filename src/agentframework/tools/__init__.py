"""Tool system for the agent framework."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    """Result from a tool execution."""

    content: str = ""
    error: str | None = None

    def __str__(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        return self.content


class Tool(ABC):
    """Base class for tools."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    @property
    def schema(self) -> dict[str, Any]:
        """Get the tool schema for LLM tool calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self._get_parameters(),
            },
        }

    @abstractmethod
    def _get_parameters(self) -> dict[str, Any]:
        """Get the parameters schema."""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given arguments."""
        pass
