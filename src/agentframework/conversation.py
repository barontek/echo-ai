"""Conversation and context-window helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class Message:
    """A message in the conversation."""

    role: Literal["user", "assistant", "system", "tool"]
    content: str
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_arguments: dict | None = None
    error_category: str | None = None


def sanitize_json(json_str: str) -> str:
    """Sanitize JSON string by removing markdown code blocks and trailing commas."""
    json_str = json_str.strip()
    json_str = re.sub(r"^```json\s*", "", json_str)
    json_str = re.sub(r"^```\s*", "", json_str)
    json_str = re.sub(r"```$", "", json_str)
    json_str = re.sub(r",(\s*[}\]])", r"\1", json_str)
    return json_str


def estimate_tokens(text: str) -> int:
    """Count tokens using tiktoken with cl100k_base encoding."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return len(text) // 4


def create_assistant_message(content: str, has_thinking: bool = False) -> Message:
    """Create an assistant message, wrapping content with thinking markers if needed."""
    if has_thinking and content:
        content = f"__THINKING__\nThinking...\n__THINKING_END__\n\n{content}"
    return Message(role="assistant", content=content)


def format_messages_for_llm(
    messages: list[Message],
    system_prompt: str = "",
    sub_agents: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Format messages for the LLM API."""
    result = []

    prompt = system_prompt
    if sub_agents:
        sub_agents_info = "\n\nAvailable sub-agents:\n"
        for name, cfg in sub_agents.items():
            sub_agents_info += f"- @{name}: {cfg.description}\n"
        prompt = system_prompt + sub_agents_info

    if prompt:
        result.append({"role": "system", "content": prompt})

    for msg in messages:
        if msg.role == "tool":
            result.append(
                {
                    "role": msg.role,
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id,
                    "name": msg.tool_name,
                }
            )
        elif msg.role == "assistant" and msg.tool_call_id:
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


def trim_messages_by_tokens(messages: list[Message], max_tokens: int) -> list[Message]:
    """Trim messages to fit within token limit, keeping most recent."""
    if max_tokens <= 0:
        return messages

    result: list[Message] = []
    total_tokens = 0

    for msg in reversed(messages):
        content = msg.content
        if msg.role == "tool" and len(content) > 10000:
            content = content[:10000] + f"\n\n[Output truncated - was {len(content)} chars]"

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
                            Message(role=messages[i - 1].role, content=messages[i - 1].content),
                        )
                    break

    return result


async def apply_context_window(
    messages: list[Message],
    max_context_messages: int,
    max_context_chars: int,
    summarize_fn: Any = None,
) -> list[Message]:
    """Apply sliding window to messages with summarization."""
    if not messages:
        return []

    if max_context_messages <= 0 and max_context_chars <= 0:
        return messages

    if max_context_messages > 0 and max_context_chars <= 0:
        return messages[-max_context_messages:]

    keep_recent_tokens = int(max_context_chars * 0.7)
    recent = trim_messages_by_tokens(messages, keep_recent_tokens)

    if len(recent) == len(messages):
        return recent[-max_context_messages:] if max_context_messages > 0 else recent

    trimmed_count = len(messages) - len(recent)
    if trimmed_count <= 2:
        return recent[-max_context_messages:] if max_context_messages > 0 else recent

    old_messages = messages[: -len(recent)] if recent else messages[:-1]

    if summarize_fn:
        summary = await summarize_fn(old_messages)
        summary_msg = Message(role="system", content=summary)
        result = [summary_msg] + recent
    else:
        result = recent

    return result[-max_context_messages:] if max_context_messages > 0 else result
