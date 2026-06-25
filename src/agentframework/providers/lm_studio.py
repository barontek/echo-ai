"""LM Studio provider — uses raw httpx for API calls (no OpenAI SDK)."""

import json
import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
)

from . import LLMProvider, LLMResponse, LLMToolCall
from ..constants import LM_STUDIO_BASE_URL, THINKING_END, THINKING_START

logger = logging.getLogger(__name__)


def _is_retryable_exception(exception: BaseException) -> bool:
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


class LMStudioProvider(LLMProvider):
    """Provider for LM Studio's local OpenAI-compatible API."""

    def __init__(
        self,
        model: str,
        base_url: str = LM_STUDIO_BASE_URL,
        api_key: str | None = None,
        timeout: int = 60,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        # Dummy key required by OpenAI client for local LM Studio API (no auth needed)
        self.api_key = api_key or "not-needed"
        self.timeout = timeout

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
        try:
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
            }
            if tools:
                payload["tools"] = tools

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                data = response.json()

            choice = data["choices"][0]
            msg = choice.get("message", {})
            content = msg.get("content", "") or ""

            tool_calls = []
            for tc in msg.get("tool_calls", []):
                args = {}
                try:
                    if tc.get("function", {}).get("arguments"):
                        args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    pass
                tool_calls.append(
                    LLMToolCall(
                        id=tc.get("id", ""),
                        name=tc.get("function", {}).get("name", ""),
                        arguments=args,
                    )
                )

            return LLMResponse(content=content, tool_calls=tool_calls)
        except Exception as e:
            logger.error("LM Studio chat failed: %s", e)
            return LLMResponse(
                content=f"LM Studio error: {str(e) or type(e).__name__}"
            )

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
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        content = ""
        tool_calls: list[LLMToolCall] = []
        in_thinking = False
        tag_leftover = ""

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})

                    reasoning = delta.get("reasoning_content")
                    if reasoning:
                        if not in_thinking and on_chunk:
                            on_chunk(THINKING_START)
                        in_thinking = True
                        if on_chunk:
                            on_chunk(reasoning)

                    text = delta.get("content")
                    if text:
                        # Handle <think> tags that may be split across chunks
                        text = tag_leftover + text
                        tag_leftover = ""
                        if "<think>" in text or "</think>" in text:
                            text = text.replace("<think>", THINKING_START).replace("</think>", THINKING_END)
                        for tag_start in ("<think", "</thin"):
                            pos = text.rfind(tag_start)
                            if pos != -1 and pos >= len(text) - len(tag_start):
                                tag_leftover = text[pos:]
                                text = text[:pos]
                                break
                        if in_thinking and on_chunk:
                            on_chunk(THINKING_END)
                        in_thinking = False
                        content += text
                        if on_chunk:
                            on_chunk(text)
                    for tc_delta in delta.get("tool_calls", []):
                        idx = tc_delta.get("index", 0)
                        while len(tool_calls) <= idx:
                            tool_calls.append(LLMToolCall(id="", name="", arguments={}))
                        tc_data = tc_delta.get("function", {})
                        if tc_delta.get("id"):
                            tool_calls[idx].id = tc_delta["id"]
                        if tc_data.get("name"):
                            tool_calls[idx].name = tc_data["name"]
                        if tc_data.get("arguments"):
                            args = {}
                            try:
                                args = json.loads(tc_data["arguments"])
                            except (json.JSONDecodeError, TypeError):
                                args = {"raw": tc_data["arguments"]}
                            tool_calls[idx].arguments = args

        return LLMResponse(
            content=content,
            tool_calls=tool_calls if any(tc.id for tc in tool_calls) else [],
        )

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
        from openai import AsyncOpenAI

        async with AsyncOpenAI(
            base_url=f"{self.base_url}/v1",
            api_key=self.api_key,
            timeout=httpx.Timeout(self.timeout, connect=30.0),
        ) as client:
            instructor_client = instructor.from_openai(
                client, mode=instructor.Mode.JSON
            )
            return await instructor_client.chat.completions.create(
                model=self.model,
                response_model=response_model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
            )

    async def list_models(self) -> list[str]:
        """List available models from LM Studio via OpenAI-compatible API."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/v1/models")
                response.raise_for_status()
                data = response.json()
                return [m["id"] for m in data.get("data", [])]
        except Exception as e:
            logger.warning("Failed to list LM Studio models: %s", e)
            return []
