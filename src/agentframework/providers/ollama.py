"""Ollama provider implementation."""

import json
import re
from typing import Any, Callable, Optional

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
)

from . import LLMProvider, LLMResponse, LLMToolCall


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider."""

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        api_key: str | None = None,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=120.0,
        )

    def _extract_tool_calls_from_content(self, content: str) -> list[LLMToolCall]:
        """Extract tool calls from markdown code blocks or plain JSON in content."""
        tool_calls = []

        # First try markdown code blocks
        pattern = r"\`\`\`(?:json)?\s*\n?(\{.*?\})\n?\`\`\`"
        matches = re.findall(pattern, content, re.DOTALL)

        # Also try to find plain JSON tool calls ({"name": "...", "arguments": ...})
        if not matches:
            pattern = r'\{\s*"name"\s*:\s*"([^"]+)"\s*,\s*"arguments"\s*:\s*(\{[^}]*\}|null)\s*\}'
            matches = re.findall(pattern, content)

        for match in matches:
            try:
                if isinstance(match, tuple):
                    # Plain JSON format
                    name = match[0]
                    args_str = match[1]
                    arguments = {} if args_str == "null" else json.loads(args_str)
                else:
                    # Markdown code block format
                    data = json.loads(match)
                    name = data.get("name", "")
                    arguments = data.get("arguments", {})
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments)

                # Skip empty/invalid tool calls
                if not name or name.lower() == "none" or name.lower() == "null":
                    continue

                tool_calls.append(
                    LLMToolCall(
                        id=f"call_{len(tool_calls)}",
                        name=name,
                        arguments=arguments,
                    )
                )
            except (json.JSONDecodeError, KeyError):
                continue

        return tool_calls

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
        """Send a chat request to Ollama."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }

        if tools:
            payload["tools"] = tools

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = await self.client.post(
                "/api/chat",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

            content = data.get("message", {}).get("content", "")
            thinking = data.get("message", {}).get("thinking", "")
            if thinking:
                content = f"__THINKING__\n{thinking}\n__THINKING_END__\n\n{content}"
            tool_calls = []

            if "tool_calls" in data.get("message", {}):
                for tc in data["message"]["tool_calls"]:
                    args = tc.get("function", {}).get("arguments", {})
                    if isinstance(args, str):
                        args = json.loads(args)
                    tool_calls.append(
                        LLMToolCall(
                            id=tc.get("id", ""),
                            name=tc.get("function", {}).get("name", ""),
                            arguments=args,
                        )
                    )

            # Also check content for markdown tool calls (qwen2.5-coder style)
            if content:
                extracted = self._extract_tool_calls_from_content(content)
                if extracted:
                    tool_calls = extracted
                    # If we extracted tool calls, clear the content since it was just the tool call
                    content = ""

            return LLMResponse(content=content, tool_calls=tool_calls)

        except httpx.HTTPStatusError as e:
            return LLMResponse(content=f"HTTP error: {e.response.status_code}")
        except Exception as e:
            return LLMResponse(content=f"Error: {str(e)}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def chat_streaming(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.3,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> LLMResponse:
        # For non-reasoning models (like qwen2.5-coder), streaming can cause issues
        # with tool call extraction. Fall back to non-streaming for these.
        # Reasoning models like qwen3 work fine with streaming.
        model_lower = self.model.lower()
        is_reasoning_model = "qwen3" in model_lower or "reasoning" in model_lower

        if not is_reasoning_model and tools:
            return await self.chat(messages, tools, temperature)

        # Use streaming for reasoning models
        return await self._chat_streaming_impl(messages, tools, temperature, on_chunk)

    async def _chat_streaming_impl(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.3,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> LLMResponse:
        """Actual streaming implementation."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }

        if tools:
            payload["tools"] = tools

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with self.client.stream(
                "POST", "/api/chat", json=payload, headers=headers
            ) as response:
                response.raise_for_status()

                content = ""
                thinking = ""
                tool_calls = []
                has_seen_non_json = False  # Track if we've seen actual text content

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg = data.get("message", {})

                    # Handle thinking (stream it with marker)
                    msg_thinking = msg.get("thinking", "")
                    if msg_thinking:
                        # Only send start marker if we haven't started thinking yet
                        if not thinking:
                            if on_chunk:
                                on_chunk("__THINKING__")
                        thinking = msg_thinking
                        if on_chunk:
                            on_chunk(msg_thinking)

                    # Handle content
                    chunk = msg.get("content", "")
                    if chunk:
                        # If we had thinking, add end marker before content
                        if thinking:
                            if on_chunk:
                                on_chunk("__THINKING_END__")
                            thinking = None  # Clear so we don't add again

                        # Skip chunks that are part of markdown tool calls or tool schemas
                        # until we've seen some normal text content
                        stripped = chunk.strip()

                        # Check if this chunk looks like it's part of JSON/technical content
                        is_technical = (
                            stripped.startswith("```")
                            or stripped in ("json", "java", "python", "text")
                            or stripped.startswith("<functions")
                            or stripped.startswith("</functions")
                            or stripped.startswith("{")
                            or stripped.startswith("}")
                            or stripped == ""
                            or (
                                len(stripped) < 20 and ":" in stripped
                            )  # Short chunks with colons are likely JSON
                        )

                        if is_technical and not has_seen_non_json:
                            # Accumulate for later extraction, but don't output yet
                            content += chunk
                            continue

                        # This is regular content
                        # If we haven't marked non-JSON yet, flush accumulated content first
                        if not has_seen_non_json:
                            if content:
                                extracted = self._extract_tool_calls_from_content(content)
                                if extracted:
                                    tool_calls.extend(extracted)
                                    content = ""
                            has_seen_non_json = True

                        content += chunk
                        if on_chunk:
                            on_chunk(chunk)

                    # Handle tool calls
                    if "tool_calls" in msg:
                        for tc in msg["tool_calls"]:
                            args = tc.get("function", {}).get("arguments", {})
                            if isinstance(args, str):
                                args = json.loads(args)
                            tool_calls.append(
                                LLMToolCall(
                                    id=tc.get("id", ""),
                                    name=tc.get("function", {}).get("name", ""),
                                    arguments=args,
                                )
                            )

                    if data.get("done"):
                        break

            # Combine thinking with content if present
            final_content = content
            if thinking:
                final_content = (
                    f"__THINKING__\n{thinking}\n__THINKING_END__\n\n{content}"
                )

            # Also check content for markdown tool calls (qwen2.5-coder style)
            if final_content:
                extracted = self._extract_tool_calls_from_content(final_content)
                if extracted:
                    # Check if content is ONLY a tool call (wrapped in markdown or plain)
                    # If so, treat it as tool call only, no text response
                    content_stripped = final_content.strip()
                    is_only_tool_call = (
                        content_stripped.startswith("```")
                        and content_stripped.endswith("```")
                        or (
                            content_stripped.startswith("{")
                            and '"name"' in content_stripped
                            and '"arguments"' in content_stripped
                        )
                    )

                    if is_only_tool_call:
                        tool_calls = extracted
                        final_content = ""
                    else:
                        # Keep any text before the tool call as the actual response
                        first_tc_start = len(final_content)
                        for tc in extracted:
                            tc_json = json.dumps(
                                {"name": tc.name, "arguments": tc.arguments}
                            )
                            pos = final_content.find(tc_json)
                            if pos >= 0 and pos < first_tc_start:
                                first_tc_start = pos

                        text_before = final_content[:first_tc_start].strip()
                        if text_before:
                            text_before = re.sub(
                                r"</?response>", "", text_before, flags=re.IGNORECASE
                            ).strip()

                        if text_before:
                            final_content = text_before
                        else:
                            tool_calls = extracted
                            final_content = ""

            return LLMResponse(content=final_content, tool_calls=tool_calls)

        except httpx.HTTPStatusError as e:
            return LLMResponse(content=f"HTTP error: {e.response.status_code}")
        except Exception as e:
            return LLMResponse(content=f"Error: {str(e)}")

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
        from openai import AsyncOpenAI

        # Ollama exposes an OpenAI compatible API at /v1
        openai_client = AsyncOpenAI(
            base_url=f"{self.base_url}/v1",
            api_key=self.api_key or "ollama"  # dummy API key required by client
        )

        # Use instructor with JSON mode for local open-source models
        instructor_client = instructor.from_openai(
            openai_client,
            mode=instructor.Mode.JSON
        )

        return await instructor_client.chat.completions.create(
            model=self.model,
            response_model=response_model,
            messages=messages,  # type: ignore
            temperature=temperature,
        )

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    def list_models(self) -> list[str]:
        """List available models (sync)."""
        import httpx

        try:
            response = httpx.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []
