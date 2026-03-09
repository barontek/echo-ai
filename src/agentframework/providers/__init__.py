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

    @abstractmethod
    async def extract_structured(
        self,
        messages: list[dict[str, str]],
        response_model: type[Any],
        temperature: float = 0.3,
    ) -> Any:
        """Extract structured data matching the given pydantic response_model."""
        pass


def get_provider(
    name: str,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> LLMProvider:
    """Get an LLM provider by name."""
    import os
    
    if name == "anthropic":
        if not (api_key or os.getenv("ANTHROPIC_API_KEY")):
            raise ValueError("ANTHROPIC_API_KEY is required for provider='anthropic'. Set it or use provider='ollama'.")
        from .anthropic import AnthropicProvider
        return AnthropicProvider(model=model, api_key=api_key)
    elif name == "openai":
        if not (api_key or os.getenv("OPENAI_API_KEY")):
            raise ValueError("OPENAI_API_KEY is required for provider='openai'. Set it or use provider='ollama'.")
        from .openai import OpenAIProvider
        return OpenAIProvider(model=model, api_key=api_key)
    elif name == "ollama":
        from .ollama import OllamaProvider
        return OllamaProvider(model=model, base_url=base_url or "http://localhost:11434", api_key=api_key)
    else:
        raise ValueError(f"Unknown provider: {name}")
