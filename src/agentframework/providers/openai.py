"""OpenAI provider implementation."""

import json
import logging
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

logger = logging.getLogger(__name__)


def _openai_error_response(retry_state) -> LLMResponse:
    """Return an LLMResponse with the error after all retries are exhausted."""
    exc = retry_state.outcome.exception()
    logger.error("OpenAI request failed after retries: %s", exc)
    return LLMResponse(content=f"OpenAI error: {exc}")


def _is_retryable_exception(exception: BaseException) -> bool:
    """Check if exception is retryable (network or rate limit)."""
    error_str = str(exception).lower()
    type_name = type(exception).__name__.lower()
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
    if any(keyword in error_str for keyword in retryable_keywords):
        return True
    # httpx timeout exceptions (ReadTimeout, ConnectTimeout, etc.) may have
    # empty str() when raised without args — match by type name instead
    return type_name.endswith("timeout")


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
        retry_error_callback=_openai_error_response,
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
                raw_args = tc.function.arguments
                if isinstance(raw_args, str):
                    try:
                        raw_args = json.loads(raw_args)
                    except (json.JSONDecodeError, TypeError):
                        raw_args = {"raw": raw_args}
                tool_calls.append(
                    LLMToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=raw_args,
                    )
                )

        return LLMResponse(content=content, tool_calls=tool_calls)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable_exception),
        retry_error_callback=_openai_error_response,
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
        tool_calls: list[LLMToolCall] = []

        async with AsyncOpenAI(
            api_key=self.api_key,
            timeout=self.timeout,
        ) as client:
            stream = await client.chat.completions.create(
                stream=True, stream_options={"include_usage": False}, **params
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    content += delta.content
                    if on_chunk:
                        on_chunk(delta.content)
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        while len(tool_calls) <= idx:
                            tool_calls.append(LLMToolCall(id="", name="", arguments={}))
                        if tc_delta.id:
                            tool_calls[idx].id = tc_delta.id
                        if tc_delta.function and tc_delta.function.name:
                            tool_calls[idx].name = tc_delta.function.name
                        if tc_delta.function and tc_delta.function.arguments:
                            args = {}
                            try:
                                args = json.loads(tc_delta.function.arguments)
                            except (json.JSONDecodeError, TypeError):
                                args = {"raw": tc_delta.function.arguments}
                            tool_calls[idx].arguments = args

        return LLMResponse(content=content, tool_calls=tool_calls if any(tc.id for tc in tool_calls) else [])

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable_exception),
        retry_error_callback=_openai_error_response,
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

    async def list_models(self) -> list[str]:
        """List available models from OpenAI."""
        try:
            base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{base.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                response.raise_for_status()
                data = response.json()
                return [m["id"] for m in data.get("data", [])]
        except Exception as e:
            logger.warning("Failed to list OpenAI models: %s", e)
            return []
