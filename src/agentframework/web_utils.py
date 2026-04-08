"""Web API utility functions for message filtering and formatting."""

import json
import re
from datetime import datetime
from typing import Any

from .constants import THINKING_END, THINKING_START

_INTERNAL_PATTERNS = [
    re.compile(r"System Note: Tools executed"),
    re.compile(r"Tool '.*' returned:"),
    re.compile(r"^FAILED: .*"),
    re.compile(r"\[Persistent Memory\]"),
]


def extract_thinking_content(content: str) -> tuple[str | None, str]:
    """Extract thinking markers from content.

    Args:
        content: Message content that may contain thinking markers.

    Returns:
        Tuple of (thinking_content, display_content).
    """
    if THINKING_START not in content or THINKING_END not in content:
        return None, content

    parts = content.split(THINKING_END, 1)
    thinking = parts[0].replace(THINKING_START, "").strip()
    display = parts[1].strip()
    return thinking, display


def normalize_tool_call(tc: Any) -> dict[str, Any]:
    """Normalize a tool call to a consistent format.

    Args:
        tc: Tool call object (dict or object with attributes).

    Returns:
        Normalized tool call dict with name, arguments, and optional result.
    """
    name = "unknown"
    args = {}
    result = None

    if isinstance(tc, dict):
        if "function" in tc:
            name = tc["function"].get("name", "unknown")
            raw_args = tc["function"].get("arguments", {})
        else:
            name = tc.get("name", "unknown")
            raw_args = tc.get("arguments", {})
        if "result" in tc:
            result = tc["result"]
    else:
        name = getattr(tc, "name", "unknown")
        raw_args = getattr(tc, "arguments", {})

    if isinstance(raw_args, str):
        args = _parse_tool_args(raw_args)
    elif isinstance(raw_args, dict):
        args = raw_args
    else:
        args = {"raw": str(raw_args)}

    tc_normalized = {"name": name, "arguments": args}
    if result:
        tc_normalized["result"] = result
    return tc_normalized


def _parse_tool_args(raw_args: str) -> dict[str, Any]:
    """Parse tool arguments from string to dict.

    Args:
        raw_args: Raw arguments as JSON string.

    Returns:
        Parsed arguments dict or {"raw": raw_args} on failure.
    """
    try:
        unescaped = raw_args.encode().decode("unicode_escape")
        return json.loads(unescaped)
    except (json.JSONDecodeError, UnicodeDecodeError):
        try:
            return json.loads(raw_args)
        except json.JSONDecodeError:
            return {"raw": raw_args}


def extract_message_fields(msg: Any) -> dict[str, Any]:
    """Extract common fields from a message object.

    Args:
        msg: Message as dict or object.

    Returns:
        Dict with role, content, metadata, timestamp, thinking, tool_calls.
    """
    role = getattr(msg, "role", msg.get("role") if isinstance(msg, dict) else "")
    content = (
        getattr(msg, "content", msg.get("content") if isinstance(msg, dict) else "")
        or ""
    )
    metadata = getattr(
        msg, "metadata", msg.get("metadata") if isinstance(msg, dict) else None
    )
    timestamp = getattr(
        msg, "timestamp", msg.get("timestamp") if isinstance(msg, dict) else ""
    )
    thinking = getattr(
        msg, "thinking", msg.get("thinking") if isinstance(msg, dict) else ""
    )
    tool_calls = getattr(
        msg, "tool_calls", msg.get("tool_calls") if isinstance(msg, dict) else None
    )

    if metadata and isinstance(metadata, dict):
        timestamp = timestamp or metadata.get("timestamp", "")
        thinking = thinking or metadata.get("thinking", "")

    return {
        "role": role,
        "content": content,
        "metadata": metadata,
        "timestamp": timestamp,
        "thinking": thinking,
        "tool_calls": tool_calls,
    }


def filter_messages_for_ui(
    messages: list[Any], session_created_at: datetime | None = None
) -> list[dict[str, Any]]:
    """Filter messages for UI rendering, removing raw tool/system noise.

    Args:
        messages: List of messages to filter.
        session_created_at: Optional session creation time for timestamp fallback.

    Returns:
        Filtered list of message dicts suitable for UI rendering.
    """
    filtered = []

    default_timestamp = (
        session_created_at.strftime("%H:%M") if session_created_at else None
    )

    for msg in messages:
        fields = extract_message_fields(msg)
        role = fields["role"]
        content = fields["content"]
        timestamp = fields["timestamp"]
        thinking = fields["thinking"]
        tool_calls = fields["tool_calls"]
        has_tools = bool(tool_calls)

        if role in ("tool", "system"):
            continue

        if not has_tools:
            if role == "assistant" and not content.strip():
                continue

            is_internal = any(pattern.search(content) for pattern in _INTERNAL_PATTERNS)
            if is_internal:
                continue

        display_thinking, display_content = extract_thinking_content(content)

        if not timestamp:
            timestamp = (
                default_timestamp
                if default_timestamp
                else datetime.now().strftime("%H:%M")
            )

        msg_dict = {
            "role": role,
            "content": display_content,
            "timestamp": timestamp,
            "has_tools": has_tools,
        }

        final_thinking = thinking or display_thinking
        if final_thinking:
            msg_dict["thinking"] = final_thinking

        if tool_calls:
            normalized = [normalize_tool_call(tc) for tc in tool_calls]
            msg_dict["tool_calls"] = normalized

        tool_results = getattr(
            msg,
            "tool_results",
            msg.get("tool_results") if isinstance(msg, dict) else None,
        )
        if tool_results and not msg_dict.get("tool_calls"):
            msg_dict["tool_results"] = tool_results

        filtered.append(msg_dict)

    return filtered
