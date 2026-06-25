"""Conversation and context-window helpers."""

from __future__ import annotations

import json
import logging
import os
import platform
from datetime import datetime
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from .constants import MESSAGE_CONTENT_MAX_CHARS, THINKING_END, THINKING_START

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_tiktoken_encoder():
    """Get or create the cached tiktoken encoder using lru_cache."""
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception as e:
        logger.debug("Failed to load tiktoken encoder: %s", e)
        return None


def _clear_tiktoken_encoder():
    """Clear the cached tiktoken encoder.

    Useful for long-running processes or testing.
    """
    _get_tiktoken_encoder.cache_clear()


@dataclass(slots=True)
class Message:
    """A message in the conversation."""

    role: Literal["user", "assistant", "system", "tool"]
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_arguments: dict | None = None
    error_category: str | None = None
    timestamp: str | None = None
    thinking: str | None = None


def sanitize_json(json_str: str) -> str:
    """Sanitize JSON string by removing markdown code blocks and trailing commas."""
    json_str = json_str.strip()
    json_str = re.sub(r"^```json\s*", "", json_str)
    json_str = re.sub(r"^```\s*", "", json_str)
    json_str = re.sub(r"```$", "", json_str)
    json_str = re.sub(r",(\s*[}\]])", r"\1", json_str)
    return json_str


def estimate_tokens(text: str) -> int:
    """Count tokens using tiktoken with cl100k_base encoding (cached)."""
    enc = _get_tiktoken_encoder()
    if enc is not None:
        return len(enc.encode(text))
    return len(text) // 4


def create_assistant_message(content: str, thinking: str | None = None) -> Message:
    """Create an assistant message, wrapping content with thinking markers if provided."""
    if thinking:
        content = f"{THINKING_START}\n{thinking}\n{THINKING_END}\n\n{content}"
    return Message(role="assistant", content=content)


def format_messages_for_llm(
    messages: list[Message],
    system_prompt: str = "",
    sub_agents: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Format messages for the LLM API."""
    result = []

    prompt = system_prompt

    # Inject dynamic context
    cwd = os.getcwd()
    os_name = platform.system()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dynamic_context = f"\n\n[System Context]\nOS: {os_name}\nCurrent Working Directory: {cwd}\nCurrent Time: {current_time}\n"

    if prompt:
        prompt += dynamic_context
    else:
        prompt = dynamic_context

    if sub_agents:
        sub_agents_info = "\nAvailable sub-agents:\n"
        for name, cfg in sub_agents.items():
            sub_agents_info += f"- @{name}: {cfg.description}\n"
        prompt += sub_agents_info

    if prompt:
        result.append({"role": "system", "content": prompt})

    for msg in messages:
        if msg.role == "assistant" and (msg.tool_calls or msg.tool_call_id):
            tool_calls = msg.tool_calls
            if not tool_calls and msg.tool_call_id:
                tool_calls = [
                    {
                        "id": msg.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": msg.tool_name or "",
                            "arguments": msg.tool_arguments or {},
                        },
                    }
                ]

            # Convert arguments from dict to JSON string (OpenAI/LM Studio format)
            if tool_calls:
                serialized = []
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    args = fn.get("arguments")
                    if isinstance(args, dict):
                        args = json.dumps(args)
                    serialized.append({**tc, "function": {**fn, "arguments": args}})
                tool_calls = serialized

            result.append(
                {
                    "role": msg.role,
                    "content": msg.content or "",
                    "tool_calls": tool_calls,
                }
            )
        elif msg.role == "tool":
            result.append(
                {
                    "role": msg.role,
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id,
                }
            )
        else:
            result.append({"role": msg.role, "content": msg.content})

    return result


def normalize_args_for_ollama(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert arguments in tool_calls from JSON strings to dicts (Ollama requirement)."""
    result = []
    for msg in messages:
        if msg.get("tool_calls"):
            normalized = []
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, TypeError):
                        args = {"raw": args}
                normalized.append({**tc, "function": {**fn, "arguments": args}})
            result.append({**msg, "tool_calls": normalized})
        else:
            result.append(msg)
    return result


def trim_messages_by_tokens(messages: list[Message], max_tokens: int) -> list[Message]:
    """Trim messages to fit within token limit, keeping most recent."""
    if max_tokens <= 0:
        return messages

    result: list[Message] = []
    total_tokens = 0

    for msg in reversed(messages):
        content = msg.content
        if msg.role == "tool" and len(content) > MESSAGE_CONTENT_MAX_CHARS:
            content = (
                content[:MESSAGE_CONTENT_MAX_CHARS] + f"\n\n[Output truncated - was {len(content)} chars]"
            )

        msg_tokens = estimate_tokens(content)
        if total_tokens + msg_tokens > max_tokens:
            break
        result.insert(
            0,
            Message(
                role=msg.role,
                content=content,
                tool_call_id=msg.tool_call_id,
                tool_name=msg.tool_name,
                tool_arguments=msg.tool_arguments,
                error_category=msg.error_category,
            ),
        )
        total_tokens += msg_tokens

    if result != messages and result:
        if result[0].role == "tool":
            for i, m in enumerate(messages):
                if m.role == "assistant" and m.tool_call_id == result[0].tool_call_id:
                    if i > 0 and messages[i - 1].role == "user":
                        result.insert(
                            0,
                            Message(
                                role=messages[i - 1].role,
                                content=messages[i - 1].content,
                            ),
                        )
                    break

    return result


def _smart_context_select(
    messages: list[Message], keep_count: int
) -> tuple[list[Message], list[Message]]:
    """Select an informative subset of messages for the LLM context window.

    Priority: system messages > tool interactions > recent context > evenly sampled.
    Returns (kept, dropped).
    """
    if len(messages) <= keep_count:
        return list(messages), []

    n = len(messages)
    must_keep: set[int] = set()

    for i, m in enumerate(messages):
        if m.role == "system":
            must_keep.add(i)

    for i, m in enumerate(messages):
        if m.tool_calls or m.tool_name:
            must_keep.add(i)

    recent_count = max(keep_count * 2 // 5, 1)
    for i in range(max(0, n - recent_count), n):
        must_keep.add(i)

    remaining_budget = keep_count - len(must_keep)
    if remaining_budget > 0:
        candidates = [i for i in range(n) if i not in must_keep]
        if candidates:
            step = max(len(candidates) // remaining_budget, 1)
            for idx in range(0, len(candidates), step):
                if len(must_keep) >= keep_count:
                    break
                must_keep.add(candidates[idx])

    sorted_indices = sorted(must_keep)[:keep_count]
    kept = [messages[i] for i in sorted_indices]
    dropped = [m for i, m in enumerate(messages) if i not in sorted_indices]
    return kept, dropped


async def apply_context_window(
    messages: list[Message],
    max_context_messages: int,
    max_context_chars: int,
    summarize_fn: Any = None,
) -> tuple[list[Message], list[Message]]:
    """Apply sliding window to messages with lazy summarization.

    Returns a tuple of (filtered_messages, dropped_messages).
    The dropped messages can be summarized in a background task.
    Uses smart selection to keep informative messages rather than blind FIFO.
    """
    if not messages:
        return [], []

    if max_context_messages <= 0 and max_context_chars <= 0:
        return messages, []

    all_dropped: list[Message] = []
    working = list(messages)

    # Step 1: Character-based token trim
    if max_context_chars > 0:
        keep_recent_tokens = int(max_context_chars * 0.7)
        recent = trim_messages_by_tokens(working, keep_recent_tokens)
        if len(recent) < len(working):
            all_dropped.extend(
                working[: -len(recent)] if recent else working[:-1]
            )
            working = recent

    # Step 2: Message-count trim with smart selection
    if max_context_messages > 0:
        kept, additional_dropped = _smart_context_select(
            working, max_context_messages
        )
        all_dropped.extend(additional_dropped)
        return kept, all_dropped

    return working, all_dropped


async def summarize_old_messages(messages_to_summarize: list[Message], llm: Any) -> str:
    """Summarize old messages using the LLM to preserve context."""
    if not messages_to_summarize:
        return ""

    conversation = []
    for msg in messages_to_summarize:
        if msg.role == "user":
            conversation.append(f"User: {msg.content[:500]}")
        elif msg.role == "assistant":
            if msg.content:
                conversation.append(f"Assistant: {msg.content[:500]}")
            if msg.tool_name:
                conversation.append(f"Assistant used tool: {msg.tool_name}")
        elif msg.role == "tool":
            tool_name = msg.tool_name or "unknown"
            content = msg.content[:300] if msg.content else ""
            conversation.append(f"Tool {tool_name} returned: {content}")

    conversation_str = chr(10).join(conversation)
    token_count = estimate_tokens(conversation_str)

    if token_count > 8000:
        chars_to_keep = 8000 * 4
        if len(conversation_str) > chars_to_keep:
            half = chars_to_keep // 2
            conversation_str = (
                conversation_str[:half]
                + "\n[...conversation truncated for summarization...]\n"
                + conversation_str[-half:]
            )

    prompt = f"""Summarize this conversation concisely, preserving key information, decisions, and any important context:

{conversation_str}

Provide a brief summary (2-3 sentences):"""

    try:
        summary_response = await llm.chat(
            messages=[{"role": "user", "content": prompt}],
            tools=None,
            temperature=0.3,
        )
        return summary_response.content or ""
    except Exception as e:
        logger.warning("Failed to summarize messages: %s", e)
        return f"[{len(messages_to_summarize)} previous messages summarized]"
