"""Tool system for the agent framework."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Type

from pydantic import BaseModel


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

    parameters_model: Type[BaseModel] | None = None

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

    def _get_parameters(self) -> dict[str, Any]:
        """Get the parameters schema. Override or define parameters_model."""
        if self.parameters_model:
            return self.parameters_model.model_json_schema()
        return {"type": "object", "properties": {}}

    @abstractmethod
    async def execute(self, *args: Any, **kwargs: Any) -> ToolResult:
        """Execute the tool with given arguments."""
        pass
