"""LLM provider base classes and implementations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class LLMResponse:
    """Response from an LLM."""

    content: str
    tool_calls: list["LLMToolCall"] = field(default_factory=list)


@dataclass
class LLMToolCall:
    """A tool call returned by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


class LLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Send a chat request to the LLM."""
        pass

    async def chat_streaming(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        on_chunk: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        """Streaming chat - override in subclass if supported."""
        raise NotImplementedError("Streaming not supported")


def get_provider(
    name: str,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> LLMProvider:
    """Get an LLM provider by name."""
    if name == "anthropic":
        from .anthropic import AnthropicProvider
        return AnthropicProvider(model=model, api_key=api_key)
    elif name == "openai":
        from .openai import OpenAIProvider
        return OpenAIProvider(model=model, api_key=api_key)
    elif name == "ollama":
        from .ollama import OllamaProvider
        return OllamaProvider(model=model, base_url=base_url or "http://localhost:11434", api_key=api_key)
    else:
        raise ValueError(f"Unknown provider: {name}")
