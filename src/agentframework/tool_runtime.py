"""Backward-compatible re-export of tool runtime.

Deprecated: Import from agentframework.core instead.
"""

from .core.tool_runtime import (
    execute_single_tool,
    execute_tool_calls,
    create_tool_result_notice,
    validate_tool_args,
    format_tool_failure,
    ToolError,
)

__all__ = [
    "execute_single_tool",
    "execute_tool_calls",
    "create_tool_result_notice",
    "validate_tool_args",
    "format_tool_failure",
    "ToolError",
]
