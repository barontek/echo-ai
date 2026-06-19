"""OpenAI provider implementation."""

import json
import os
from typing import Any

import httpx
from openai import AsyncOpenAI
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
)

from . import LLMProvider, LLMResponse, LLMToolCall


def _is_retryable_exception(exception: BaseException) -> bool:
    """Check if exception is retryable (network or rate limit)."""
    error_str = str(exception).lower()
    retryable_keywords = [
        "rate limit",
        "too many requests",
        "429",
        "connection",
        "timeout",
        "network",
        "temporarily unavailable",
        "service unavailable",
        "502",
        "503",
        "504",
    ]
    return any(keyword in error_str for keyword in retryable_keywords)


class OpenAIProvider(LLMProvider):
    """OpenAI provider."""

    def __init__(self, model: str, api_key: str | None = None, timeout: int = 60):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.timeout = httpx.Timeout(timeout, connect=30.0)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable_exception),
        reraise=True,
    )
    async def chat(
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

        async with AsyncOpenAI(
            api_key=self.api_key,
            timeout=self.timeout,
        ) as client:
            response = await client.chat.completions.create(**params)

        msg = response.choices[0].message
        content = msg.content or ""

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(
                    LLMToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=tc.function.arguments,
                    )
                )

        return LLMResponse(content=content, tool_calls=tool_calls)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable_exception),
        reraise=True,
    )
    async def chat_streaming(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        on_chunk: Any | None = None,
    ) -> LLMResponse:
        """Send a streaming chat request to OpenAI."""
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        if tools:
            params["tools"] = tools

        content = ""

        async with AsyncOpenAI(
            api_key=self.api_key,
            timeout=self.timeout,
        ) as client:
            async with client.chat.completions.stream(**params) as stream:
                async for event in stream:
                    if event.type == "content.delta":
                        content += event.delta
                        if on_chunk:
                            on_chunk(event.delta)

                final_completion = await stream.get_final_completion()

        msg = final_completion.choices[0].message

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = {}
                try:
                    if tc.function.arguments:
                        args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    pass
                tool_calls.append(
                    LLMToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        return LLMResponse(content=content, tool_calls=tool_calls)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable_exception),
        reraise=True,
    )
    async def extract_structured(
        self,
        messages: list[dict[str, str]],
        response_model: type[Any],
        temperature: float = 0.3,
    ) -> Any:
        import instructor

        async with AsyncOpenAI(
            api_key=self.api_key,
            timeout=self.timeout,
        ) as client:
            instructor_client = instructor.from_openai(client)
            return await instructor_client.chat.completions.create(
                model=self.model,
                response_model=response_model,
                messages=messages,  # type: ignore
                temperature=temperature,
            )
