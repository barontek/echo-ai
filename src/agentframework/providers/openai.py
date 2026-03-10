"""OpenAI provider implementation."""

import os
from typing import Any

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

    def __init__(self, model: str, api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")

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

        async with AsyncOpenAI(api_key=self.api_key) as client:
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
            "stream": True,
        }

        if tools:
            params["tools"] = tools

        content = ""
        tool_calls_dict = {}

        async with AsyncOpenAI(api_key=self.api_key) as client:
            response = await client.chat.completions.create(**params)

            async for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if not delta:
                    continue
    
                if delta.content:
                    content += delta.content
                    if on_chunk:
                        on_chunk(delta.content)

                if getattr(delta, "tool_calls", None):
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_dict:
                            tool_calls_dict[idx] = {"id": tc.id, "name": tc.function.name, "arguments": ""}
                        if tc.function and tc.function.arguments:
                            tool_calls_dict[idx]["arguments"] += tc.function.arguments

        tool_calls = []
        import json
        for _, tc in sorted(tool_calls_dict.items()):
            args = {}
            try:
                if tc["arguments"]:
                    args = json.loads(tc["arguments"])
            except json.JSONDecodeError:
                pass
            tool_calls.append(
                LLMToolCall(
                    id=tc["id"] or "",
                    name=tc["name"] or "",
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
        
        async with AsyncOpenAI(api_key=self.api_key) as client:
            instructor_client = instructor.from_openai(client)
            return await instructor_client.chat.completions.create(
                model=self.model,
                response_model=response_model,
                messages=messages,  # type: ignore
                temperature=temperature,
            )
