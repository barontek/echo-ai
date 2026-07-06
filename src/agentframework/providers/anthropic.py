"""Anthropic provider implementation."""

import logging
import os
from collections.abc import Callable
from typing import Any

import httpx
from anthropic import AsyncAnthropic
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
)

from ..constants import DEFAULT_MAX_TOKENS
from . import LLMProvider, LLMResponse, LLMToolCall

logger = logging.getLogger(__name__)


def _anthropic_error_response(retry_state) -> LLMResponse:
    """Return an LLMResponse with the error after all retries are exhausted."""
    exc = retry_state.outcome.exception()
    logger.error("Anthropic chat failed after retries: %s", exc)
    return LLMResponse(content=f"Anthropic error: {exc}")


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider."""

    def __init__(self, model: str, api_key: str | None = None, timeout: int = 60):
        self.model = model
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.timeout = httpx.Timeout(timeout, connect=30.0)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry_error_callback=_anthropic_error_response,
    )
    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Send a chat request to Anthropic."""
        system_parts: list[str] = []
        filtered_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_parts.append(msg["content"])
            else:
                filtered_messages.append(msg)

        if not filtered_messages:
            logger.warning("All messages are system messages; cannot call Anthropic API")
            return LLMResponse(content="")

        system_msg = "\n".join(system_parts) if system_parts else None

        params = {
            "model": self.model,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "messages": filtered_messages,
            "temperature": temperature,
        }

        if system_msg:
            params["system"] = system_msg

        if tools:
            params["tools"] = tools

        async with AsyncAnthropic(
            api_key=self.api_key,
            timeout=self.timeout,
        ) as client:
            response = await client.messages.create(**params)

        content = ""
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    LLMToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input,
                    )
                )

        return LLMResponse(content=content, tool_calls=tool_calls)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def chat_streaming(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        on_chunk: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        """Send a streaming chat request to Anthropic."""
        system_parts: list[str] = []
        filtered_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_parts.append(msg["content"])
            else:
                filtered_messages.append(msg)

        if not filtered_messages:
            logger.warning("All messages are system messages; cannot call Anthropic API")
            return LLMResponse(content="")

        system_msg = "\n".join(system_parts) if system_parts else None

        params = {
            "model": self.model,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "messages": filtered_messages,
            "temperature": temperature,
        }

        if system_msg:
            params["system"] = system_msg

        if tools:
            params["tools"] = tools

        content = ""
        tool_calls = []

        async with AsyncAnthropic(
            api_key=self.api_key,
            timeout=self.timeout,
        ) as client:
            async with client.messages.stream(**params) as stream:
                async for text in stream.text_stream:
                    content += text
                    if on_chunk:
                        on_chunk(text)

            final_message = await stream.get_final_message()
            for block in final_message.content:
                if block.type == "tool_use":
                    tool_calls.append(
                        LLMToolCall(
                            id=block.id,
                            name=block.name,
                            arguments=block.input,
                        )
                    )

        return LLMResponse(content=content, tool_calls=tool_calls)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry_error_callback=_anthropic_error_response,
    )
    async def extract_structured(
        self,
        messages: list[dict[str, str]],
        response_model: type[Any],
        temperature: float = 0.3,
    ) -> Any:
        import instructor

        async with AsyncAnthropic(
            api_key=self.api_key,
            timeout=self.timeout,
        ) as client:
            instructor_client = instructor.from_anthropic(client)

            system_parts = []
            filtered_messages = []

            for msg in messages:
                if msg.get("role") == "system":
                    system_parts.append(msg["content"])
                else:
                    filtered_messages.append(msg)

            params = {
                "model": self.model,
                "max_tokens": DEFAULT_MAX_TOKENS,
                "messages": filtered_messages,
                "temperature": temperature,
                "response_model": response_model,
            }

            if system_parts:
                params["system"] = "\n".join(system_parts)

            return await instructor_client.chat.completions.create(**params)
