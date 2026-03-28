"""Backward-compatible re-export of session runtime.

Deprecated: Import from agentframework.core instead.
"""

from .core.session_runtime import (
    undo_change,
    redo_change,
    serialize_messages,
    deserialize_messages,
)

__all__ = ["undo_change", "redo_change", "serialize_messages", "deserialize_messages"]
