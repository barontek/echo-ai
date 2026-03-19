"""Anthropic provider implementation."""

import os
from typing import Any

from anthropic import AsyncAnthropic
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
)

from . import LLMProvider, LLMResponse, LLMToolCall


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider."""

    def __init__(self, model: str, api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Send a chat request to Anthropic."""
        system_msg = None
        filtered_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_msg = msg["content"]
            else:
                filtered_messages.append(msg)

        params = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": filtered_messages,
            "temperature": temperature,
        }

        if system_msg:
            params["system"] = system_msg

        if tools:
            params["tools"] = tools

        async with AsyncAnthropic(api_key=self.api_key) as client:
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
        on_chunk: Any | None = None,
    ) -> LLMResponse:
        """Send a streaming chat request to Anthropic."""
        system_msg = None
        filtered_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_msg = msg["content"]
            else:
                filtered_messages.append(msg)

        params = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": filtered_messages,
            "temperature": temperature,
        }

        if system_msg:
            params["system"] = system_msg

        if tools:
            params["tools"] = tools

        content = ""
        tool_calls = []

        async with AsyncAnthropic(api_key=self.api_key) as client:
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
        reraise=True,
    )
    async def extract_structured(
        self,
        messages: list[dict[str, str]],
        response_model: type[Any],
        temperature: float = 0.3,
    ) -> Any:
        import instructor

        async with AsyncAnthropic(api_key=self.api_key) as client:
            instructor_client = instructor.from_anthropic(client)

            filtered_messages = []

            for msg in messages:
                if msg.get("role") == "system":
                    pass
                else:
                    filtered_messages.append(msg)

            params = {
                "model": self.model,
                "max_tokens": 4096,
                "messages": filtered_messages,
                "temperature": temperature,
                "response_model": response_model,
            }

            # NOTE: Not all anthropic versions in instructor might natively accept "system" as kwargs in completions
            # Instructor documentation notes passing it within messages normally is fine.

            return await instructor_client.chat.completions.create(**params)
