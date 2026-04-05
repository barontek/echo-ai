"""Session/change-tracker runtime helpers."""

from __future__ import annotations

from pathlib import Path

from ..conversation import Message


def undo_change(change_tracker) -> str:
    if not change_tracker.can_undo():
        return "Nothing to undo."

    change = change_tracker.undo()
    if change is None:
        return "Nothing to undo."

    if change["old_content"] is not None:
        try:
            Path(change["path"]).write_text(change["old_content"])
            return f"Undid write to {change['path']}"
        except Exception as e:
            return f"Undo failed: {e}"
    return f"Undid {change['operation']} on {change['path']}"


def redo_change(change_tracker) -> str:
    if not change_tracker.can_redo():
        return "Nothing to redo."

    change = change_tracker.redo()
    if change is None:
        return "Nothing to redo."

    if change["new_content"] is not None:
        try:
            Path(change["path"]).write_text(change["new_content"])
            return f"Redid write to {change['path']}"
        except Exception as e:
            return f"Redo failed: {e}"
    return f"Redid {change['operation']} on {change['path']}"


def serialize_messages(messages: list[Message]) -> list[dict]:
    return [
        {
            "role": m.role,
            "content": m.content,
            "tool_calls": m.tool_calls,
            "tool_call_id": m.tool_call_id,
            "tool_name": m.tool_name,
            "tool_arguments": m.tool_arguments,
            "error_category": m.error_category,
            "timestamp": getattr(m, "timestamp", None),
        }
        for m in messages
    ]


def deserialize_messages(messages: list[dict]) -> list[Message]:
    result = []
    for m in messages:
        msg = Message(
            role=m["role"],
            content=m["content"],
            tool_calls=m.get("tool_calls"),
            tool_call_id=m.get("tool_call_id"),
            tool_name=m.get("tool_name"),
            tool_arguments=m.get("tool_arguments"),
            error_category=m.get("error_category"),
        )
        if "timestamp" in m:
            msg.timestamp = m["timestamp"]
        result.append(msg)
    return result
