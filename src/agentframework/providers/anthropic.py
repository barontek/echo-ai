"""Anthropic provider implementation."""

import os
from typing import Any

from anthropic import AsyncAnthropic

from . import LLMProvider, LLMResponse, LLMToolCall


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider."""

    def __init__(self, model: str, api_key: str | None = None):
        self.model = model
        self.client = AsyncAnthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))

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

        response = await self.client.messages.create(**params)

        content = ""
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append(LLMToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                ))

        return LLMResponse(content=content, tool_calls=tool_calls)
