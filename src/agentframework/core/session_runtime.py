"""Session/change-tracker runtime helpers."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any

from ..conversation import Message


def _validate_path_safe(path: str) -> bool:
    """Basic safety check: ensure path doesn't escape via parent dir traversal."""
    if ".." in Path(path).parts:
        return False
    return True


def undo_change(change_tracker: Any) -> str:
    if not change_tracker.can_undo():
        return "Nothing to undo."

    change = change_tracker.undo()
    if change is None:
        return "Nothing to undo."

    path = change.get("path")
    if not path:
        return "Undo failed: no path in change record."
    if not _validate_path_safe(path):
        return f"Undo failed: unsafe path {path}"

    old_content = change.get("old_content")
    if old_content is not None:
        try:
            Path(path).write_text(old_content, encoding="utf-8")
            return f"Undid write to {path}"
        except Exception as e:
            return f"Undo failed: {e}"
    else:
        # File was newly created — undo should delete it
        try:
            Path(path).unlink(missing_ok=True)
            return f"Undid creation of {path}"
        except Exception as e:
            return f"Undo failed: {e}"


def redo_change(change_tracker: Any) -> str:
    if not change_tracker.can_redo():
        return "Nothing to redo."

    change = change_tracker.redo()
    if change is None:
        return "Nothing to redo."

    path = change.get("path")
    if not path:
        return "Redo failed: no path in change record."
    if not _validate_path_safe(path):
        return f"Redo failed: unsafe path {path}"

    new_content = change.get("new_content")
    if new_content is not None:
        try:
            Path(path).write_text(new_content, encoding="utf-8")
            return f"Redid write to {path}"
        except Exception as e:
            return f"Redo failed: {e}"
    else:
        # File was deleted — redo should re-delete it
        try:
            Path(path).unlink(missing_ok=True)
            return f"Redid deletion of {path}"
        except Exception as e:
            return f"Redo failed: {e}"


_MESSAGE_FIELDS = {f.name for f in fields(Message)}


def serialize_messages(messages: list[Message]) -> list[dict]:
    return [{f: getattr(m, f) for f in _MESSAGE_FIELDS} for m in messages]


def deserialize_messages(messages: list[dict]) -> list[Message]:
    result: list[Message] = []
    for m in messages:
        kwargs: dict[str, Any] = {}
        for f in _MESSAGE_FIELDS:
            val = m.get(f)
            if val is not None:
                kwargs[f] = val
        result.append(Message(**kwargs))
    return result
