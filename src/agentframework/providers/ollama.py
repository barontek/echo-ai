"""Ollama provider implementation."""

import json
import logging
import re
from typing import Any, Callable, Optional

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
)

from . import LLMProvider, LLMResponse, LLMToolCall
from ..constants import OLLAMA_BASE_URL, THINKING_END, THINKING_START
from ..conversation import normalize_args_for_ollama

logger = logging.getLogger(__name__)

COMMON_TOOL_NAMES = frozenset(
    [
        "bash",
        "web_search",
        "web_fetch",
        "read_file",
        "write_file",
        "grep",
        "glob",
        "list_dir",
        "search",
        "notes",
        "memory",
        "call",
        "create_directory",
        "delete_file",
        "rename",
        "move",
        "copy",
        "patch",
        "apply",
        "list",
        "move_to_trash",
        "restore",
        "read",
        "write",
        "find",
        "ls",
        "dir",
        "cat",
        "head",
        "tail",
        "wc",
        "sort",
        "uniq",
        "cut",
        "awk",
        "sed",
        "git",
        "pip",
        "npm",
        "make",
        "docker",
        "curl",
        "wget",
        "ssh",
    ]
)


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider."""

    def __init__(
        self,
        model: str,
        base_url: str = OLLAMA_BASE_URL,
        api_key: str | None = None,
        timeout: int = 60,
        num_ctx: int | None = None,
    ):
        import httpx

        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.num_ctx = num_ctx
        self.timeout = httpx.Timeout(timeout, connect=30.0)
        self.stream_timeout = httpx.Timeout(timeout * 5, connect=30.0)
        self.client = httpx.AsyncClient(timeout=self.stream_timeout)

    def _extract_tool_calls_from_content(
        self,
        content: str,
        native_tool_calls: list[dict] | None = None,
    ) -> list[LLMToolCall]:
        """Extract tool calls from markdown code blocks, plain JSON, or native API field."""
        if native_tool_calls:
            tool_calls = []
            for tc in native_tool_calls:
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
            return tool_calls

        tool_calls = []

        # First try markdown code blocks
        # Use greedy match for the content between the first { and last } inside the code block
        # to handle nested JSON objects (e.g. arguments with nested objects).
        pattern = r"\`\`\`(?:json)?\s*\n?(\{.*\}).*\n?\`\`\`"
        matches = re.findall(pattern, content, re.DOTALL)
        extraction_method = "markdown block"

        # Also try to find plain JSON tool calls ({"name": "...", "arguments": ...})
        if not matches:
            pattern = r'\{\s*"name"\s*:\s*"([^"]+)"\s*,\s*"arguments"\s*:\s*(\{[^}]*\}|null)\s*\}'
            matches = re.findall(pattern, content)
            extraction_method = "plain JSON"

        # Also try to find tool name followed by JSON arguments (e.g. "web_search{\"query\": \"test\"}")
        # Sort by length descending to match longer names first (e.g. web_search before search)
        if not matches:
            for tool_name in sorted(COMMON_TOOL_NAMES, key=len, reverse=True):
                # Match tool name followed by {JSON}
                pattern = rf"\b({re.escape(tool_name)})\s*(\{{[^}}]+}})"
                simple_matches = re.findall(pattern, content)
                if simple_matches:
                    for name, args_str in simple_matches:
                        try:
                            arguments = json.loads(args_str)
                            logger.warning(
                                "Extracted tool call '%s' via name-prefix heuristic extraction",
                                name,
                            )
                            tool_calls.append(
                                LLMToolCall(
                                    id=f"call_{len(tool_calls)}",
                                    name=name,
                                    arguments=arguments,
                                )
                            )
                        except json.JSONDecodeError:
                            continue
                    if tool_calls:
                        break
            if tool_calls:
                return tool_calls

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

                logger.warning(
                    "Extracted tool call '%s' via %s extraction",
                    name,
                    extraction_method,
                )
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
        messages = normalize_args_for_ollama(messages)
        options = {}
        if self.num_ctx is not None:
            options["num_ctx"] = self.num_ctx

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if options:
            payload["options"] = options

        if tools:
            payload["tools"] = tools

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            logger.debug(
                "ollama_chat_request",
                extra={
                    "model": self.model,
                    "message_count": len(messages),
                    "tools": [t["function"]["name"] for t in tools] if tools else [],
                },
            )

            response = await self.client.post(
                f"{self.base_url}/api/chat",
                json=payload,
                headers=headers,
                timeout=self.timeout,  # Configurable timeout for non-streaming requests
            )
            response.raise_for_status()
            data = response.json()

            content = data.get("message", {}).get("content", "")
            thinking = data.get("message", {}).get("thinking", "")

            # FIX: Translate inline <think> tags for models that put thoughts in content
            if "<think>" in content:
                content = content.replace("<think>", THINKING_START + "\n")
                content = content.replace("</think>", "\n" + THINKING_END)

            if thinking and THINKING_START not in content:
                content = f"{THINKING_START}\n{thinking}\n{THINKING_END}\n\n{content}"
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
            if content and not tool_calls:
                extracted = self._extract_tool_calls_from_content(content)
                if extracted:
                    tool_calls = extracted
                    # If we extracted tool calls, clear the content since it was just the tool call
                    content = ""

            return LLMResponse(
                content=content, thinking=thinking, tool_calls=tool_calls
            )

        except httpx.HTTPStatusError as e:
            logger.warning("Ollama HTTP error: %s", e.response.status_code)
            return LLMResponse(content=f"HTTP error: {e.response.status_code}")
        except Exception as e:
            logger.error("Ollama chat failed: %s", e)
            return LLMResponse(
                content="An internal error occurred while processing your request."
            )

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
        # Always use streaming for all models
        return await self._chat_streaming_impl(messages, tools, temperature, on_chunk)

    async def _chat_streaming_impl(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.3,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> LLMResponse:
        """Actual streaming implementation."""
        messages = normalize_args_for_ollama(messages)
        options = {}
        if self.num_ctx is not None:
            options["num_ctx"] = self.num_ctx

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if options:
            payload["options"] = options

        if tools:
            payload["tools"] = tools

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            logger.debug(
                "ollama_streaming_request",
                extra={
                    "model": self.model,
                    "message_count": len(messages),
                    "tools": [t["function"]["name"] for t in tools] if tools else [],
                },
            )

            async with self.client.stream(
                "POST", f"{self.base_url}/api/chat", json=payload, headers=headers
            ) as response:
                response.raise_for_status()

                content = ""
                thinking = ""
                thinking_ended = False  # FIX: Use a flag instead of clearing the string
                tool_calls = []
                has_seen_non_json = False  # Track if we've seen actual text content
                tag_leftover = ""  # Partial <think>/</think> tag left over from previous chunk

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
                        if not thinking:
                            if on_chunk:
                                on_chunk(THINKING_START)
                        thinking += msg_thinking
                        if on_chunk:
                            on_chunk(msg_thinking)

                    chunk = msg.get("content", "")
                    if chunk:
                        if thinking and not thinking_ended:
                            if on_chunk:
                                on_chunk(THINKING_END)
                            thinking_ended = (
                                True  # FIX: Use flag so thinking string isn't lost
                            )

                        # Handle <think>/</think> tags that may be split across chunks
                        # by accumulating partial tags until the full tag is seen
                        chunk = tag_leftover + chunk
                        tag_leftover = ""

                        if "<think>" in chunk or "</think>" in chunk:
                            chunk = chunk.replace("<think>", THINKING_START)
                            chunk = chunk.replace("</think>", THINKING_END)

                        # Check if chunk ends with an incomplete tag boundary
                        # (max partial tag length is 7 for e.g. "<think>" without ">")
                        for tag_start in ("<think", "</thin"):
                            pos = chunk.rfind(tag_start)
                            if pos != -1 and pos >= len(chunk) - len(tag_start):
                                tag_leftover = chunk[pos:]
                                chunk = chunk[:pos]
                                break

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
                            or stripped in COMMON_TOOL_NAMES
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
                                extracted = self._extract_tool_calls_from_content(
                                    content
                                )
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

            # Flush any remaining content from the tag leftover
            if tag_leftover:
                tag_leftover = (
                    tag_leftover.replace("<think>", THINKING_START).replace(
                        "</think>", THINKING_END
                    )
                )
                if has_seen_non_json:
                    content += tag_leftover
                    if on_chunk:
                        on_chunk(tag_leftover)
                else:
                    content += tag_leftover

            # Catch any raw tags that slipped through split boundaries
            content = content.replace("<think>", THINKING_START).replace(
                "</think>", THINKING_END
            )

            # Also check content for markdown tool calls (qwen2.5-coder style)
            if content:
                extracted = self._extract_tool_calls_from_content(content)
                if extracted:
                    # Check if content is ONLY a tool call (wrapped in markdown, JSON, or plain text)
                    # If so, treat it as tool call only, no text response
                    content_stripped = content.strip()
                    is_only_tool_call = (
                        content_stripped.startswith("```")
                        and content_stripped.endswith("```")
                        or (
                            content_stripped.startswith("{")
                            and '"name"' in content_stripped
                            and '"arguments"' in content_stripped
                        )
                        or content_stripped in COMMON_TOOL_NAMES
                    )

                    if is_only_tool_call:
                        tool_calls = extracted
                        content = ""
                    else:
                        # Keep any text before the tool call as the actual response
                        first_tc_start = len(content)
                        for tc in extracted:
                            tc_json = json.dumps(
                                {"name": tc.name, "arguments": tc.arguments}
                            )
                            pos = content.find(tc_json)
                            if pos >= 0 and pos < first_tc_start:
                                first_tc_start = pos

                        text_before = content[:first_tc_start].strip()
                        if text_before:
                            text_before = re.sub(
                                r"</?response>", "", text_before, flags=re.IGNORECASE
                            ).strip()

                        if text_before:
                            content = text_before
                        else:
                            tool_calls = extracted
                            content = ""

            return LLMResponse(
                content=content, thinking=thinking, tool_calls=tool_calls
            )

        except httpx.HTTPStatusError as e:
            logger.warning("Ollama streaming HTTP error: %s", e.response.status_code)
            return LLMResponse(content=f"HTTP error: {e.response.status_code}")
        except Exception as e:
            logger.error("Ollama streaming failed: %s", e)
            return LLMResponse(
                content="An internal error occurred while processing your request."
            )

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
            api_key=self.api_key or "ollama",  # dummy API key required by client
        )

        # Use instructor with JSON mode for local open-source models
        instructor_client = instructor.from_openai(
            openai_client, mode=instructor.Mode.JSON
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
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=30.0)
            response.raise_for_status()
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.warning("Failed to list Ollama models: %s", e)
            return []
