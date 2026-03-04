"""OpenAI provider implementation."""

import os
from typing import Any

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from . import LLMProvider, LLMResponse, LLMToolCall


def _is_retryable_exception(exception: Exception) -> bool:
    """Check if exception is retryable (network or rate limit)."""
    error_str = str(exception).lower()
    retryable_keywords = [
        "rate limit", "too many requests", "429",
        "connection", "timeout", "network", "temporarily unavailable",
        "service unavailable", "502", "503", "504"
    ]
    return any(keyword in error_str for keyword in retryable_keywords)


class OpenAIProvider(LLMProvider):
    """OpenAI provider."""

    def __init__(self, model: str, api_key: str | None = None):
        self.model = model
        self.client = AsyncOpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
        before_sleep=lambda retry_state: (
            setattr(retry_state.exception(), 'is_retryable', _is_retryable_exception(retry_state.exception()))
            if hasattr(retry_state, 'exception') and retry_state.exception() else None
        ),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
    ) -> LLMResponse:
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Send a chat request to OpenAI."""
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        if tools:
            params["tools"] = tools

        response = await self.client.chat.completions.create(**params)

        msg = response.choices[0].message
        content = msg.content or ""

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(LLMToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                ))

        return LLMResponse(content=content, tool_calls=tool_calls)
