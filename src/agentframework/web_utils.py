"""Web API utility functions for message filtering and formatting."""

import json
import re
from datetime import datetime
from typing import Any



_INTERNAL_PATTERNS = [
    re.compile(r"^FAILED: .*"),
    re.compile(r"\[Persistent Memory\]"),
]


def extract_thinking_content(content: str) -> tuple[str | None, str]:
    """Extract thinking markers from content.

    Args:
        content: Message content that may contain <think> tags.

    Returns:
        Tuple of (thinking_content, display_content).
    """
    if "<think>" not in content:
        return None, content

    if "</think>" in content:
        parts = content.split("</think>", 1)
        thinking = parts[0].replace("<think>", "").strip()
        display = parts[1].strip()
        return thinking, display

    _, after = content.split("<think>", 1)
    return after.strip(), ""


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
        return json.loads(raw_args)
    except json.JSONDecodeError:
        try:
            unescaped = raw_args.encode().decode("unicode_escape")
            return json.loads(unescaped)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"raw": raw_args}


def _get_msg_field(msg: Any, field: str, default: Any = "") -> Any:
    """Get a field from a message that may be a dict or an object."""
    if isinstance(msg, dict):
        return msg.get(field, default)
    return getattr(msg, field, default)


def extract_message_fields(msg: Any) -> dict[str, Any]:
    """Extract common fields from a message object.

    Args:
        msg: Message as dict or object.

    Returns:
        Dict with role, content, id, metadata, timestamp, thinking, tool_calls.
    """
    role = _get_msg_field(msg, "role", "")
    content = _get_msg_field(msg, "content", "") or ""
    msg_id = _get_msg_field(msg, "id", None)
    metadata = _get_msg_field(msg, "metadata", None)
    timestamp = _get_msg_field(msg, "timestamp", "")
    thinking = _get_msg_field(msg, "thinking", "")
    tool_calls = _get_msg_field(msg, "tool_calls", None)

    if metadata and isinstance(metadata, dict):
        timestamp = timestamp or metadata.get("timestamp", "")
        thinking = thinking or metadata.get("thinking", "")

    return {
        "role": role,
        "content": content,
        "id": msg_id,
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
    # Build tool_call_id -> result mapping from tool messages
    result_map: dict[str, dict] = {}
    for msg in messages:
        if isinstance(msg, dict):
            if msg.get("role") == "tool":
                tc_id = msg.get("tool_call_id")
                if tc_id:
                    result_map[tc_id] = {
                        "content": msg.get("content"),
                        "error": msg.get("error_category"),
                    }
        elif getattr(msg, "role", None) == "tool":
            tc_id = getattr(msg, "tool_call_id", None)
            if tc_id:
                result_map[tc_id] = {
                    "content": getattr(msg, "content", None),
                    "error": getattr(msg, "error_category", None),
                }

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

        if role == "assistant" and not content.strip() and not tool_calls:
            continue

        is_internal = any(pattern.search(content) for pattern in _INTERNAL_PATTERNS)
        if is_internal:
            continue

        if thinking and "<think>" not in content:
            content = f"<think>\n{thinking}\n</think>\n\n{content}"

        if not timestamp:
            timestamp = default_timestamp if default_timestamp else datetime.now().strftime("%H:%M")

        msg_id = fields.get("id")
        msg_dict = {
            "role": role,
            "content": content,
            "timestamp": timestamp,
            "has_tools": has_tools,
        }

        if msg_id:
            msg_dict["id"] = msg_id

        if tool_calls:
            normalized = [normalize_tool_call(tc) for tc in tool_calls]
            # Attach results from corresponding "role": "tool" messages
            for tc, ntc in zip(tool_calls, normalized):
                tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                if tc_id and tc_id in result_map:
                    ntc["result"] = result_map[tc_id]
            msg_dict["tool_calls"] = normalized

        tool_results = getattr(
            msg,
            "tool_results",
            msg.get("tool_results") if isinstance(msg, dict) else None,
        )
        if tool_results:
            msg_dict["tool_results"] = tool_results

        filtered.append(msg_dict)

    return filtered
