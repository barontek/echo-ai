"""Tool execution runtime helpers with structured error categories."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from time import perf_counter

from .conversation import Message, sanitize_json
from .providers import LLMToolCall
from .session import ChangeTracker
from .tools import Tool

logger = logging.getLogger(__name__)


@dataclass
class ToolError:
    category: str
    message: str


ERROR_TEXT = {
    "validation_error": "Invalid tool arguments",
    "policy_denied": "Operation blocked by safety policy",
    "execution_error": "Tool execution failed",
    "tool_not_found": "Unknown tool",
}


def format_tool_failure(error: ToolError) -> str:
    label = ERROR_TEXT.get(error.category, "Tool error")
    return f"FAILED [{error.category}] - {label}: {error.message}"


def validate_tool_args(tool: Tool, args: dict) -> tuple[ToolError | None, dict | None]:
    """Validate tool arguments using Pydantic."""
    if not tool.parameters_model:
        return None, args

    try:
        validated = tool.parameters_model.model_validate(args)
        return None, validated.model_dump()
    except Exception as e:
        return ToolError("validation_error", f"Validation error: {e}"), None


async def execute_single_tool(
    tool_call: LLMToolCall,
    tool_map: dict[str, Tool],
    change_tracker: ChangeTracker | None = None,
) -> tuple[Message, float]:
    """Execute a single tool call and return the result message + duration seconds."""
    started = perf_counter()
    tool = tool_map.get(tool_call.name)
    if not tool:
        err = ToolError("tool_not_found", f"Unknown tool: {tool_call.name}")
        return (
            Message(
                role="tool",
                content=format_tool_failure(err),
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                tool_arguments=tool_call.arguments,
                error_category=err.category,
            ),
            perf_counter() - started,
        )

    try:
        args = tool_call.arguments
        if isinstance(args, str):
            try:
                args = json.loads(sanitize_json(args))
            except json.JSONDecodeError:
                err = ToolError("validation_error", f"Invalid JSON in arguments: {args}")
                return (
                    Message(
                        role="tool",
                        content=format_tool_failure(err),
                        tool_call_id=tool_call.id,
                        tool_name=tool_call.name,
                        tool_arguments=tool_call.arguments,
                        error_category=err.category,
                    ),
                    perf_counter() - started,
                )

        validation_error, validated_args = validate_tool_args(tool, args)
        if validation_error:
            return (
                Message(
                    role="tool",
                    content=format_tool_failure(validation_error),
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    tool_arguments=tool_call.arguments,
                    error_category=validation_error.category,
                ),
                perf_counter() - started,
            )

        result = await tool.execute(**validated_args)

        if change_tracker and tool_call.name == "write_file" and validated_args and "path" in validated_args:
            try:
                from pathlib import Path

                old_content = None
                if Path(args["path"]).exists():
                    old_content = Path(args["path"]).read_text()
                change_tracker.record_change("write", args["path"], old_content, args.get("content"))
            except Exception:
                pass

        if result.error:
            msg = Message(
                role="tool",
                content=format_tool_failure(ToolError("policy_denied", result.error)),
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                tool_arguments=tool_call.arguments,
                error_category="policy_denied",
            )
        else:
            msg = Message(
                role="tool",
                content=result.content or "",
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                tool_arguments=tool_call.arguments,
            )

        return msg, perf_counter() - started
    except TypeError as e:
        error_msg = str(e)
        if "missing" in error_msg or "required" in error_msg:
            msg = f"Missing required argument: {error_msg}"
        elif "unexpected keyword" in error_msg:
            msg = f"Invalid argument: {error_msg}"
        else:
            msg = f"Argument error: {error_msg}"
        err = ToolError("validation_error", msg)
        return (
            Message(
                role="tool",
                content=format_tool_failure(err),
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                tool_arguments=tool_call.arguments,
                error_category=err.category,
            ),
            perf_counter() - started,
        )
    except Exception as e:
        logger.exception("Tool %s failed", tool_call.name)
        err = ToolError("execution_error", str(e))
        return (
            Message(
                role="tool",
                content=format_tool_failure(err),
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                tool_arguments=tool_call.arguments,
                error_category=err.category,
            ),
            perf_counter() - started,
        )


async def execute_tool_calls(
    tool_calls: list[LLMToolCall],
    tool_map: dict[str, Tool],
    parallel: bool = False,
    change_tracker: ChangeTracker | None = None,
) -> tuple[list[Message], dict[str, float]]:
    """Execute tool calls and return result messages and timings by tool call id."""

    async def execute_and_message(tc: LLMToolCall):
        return await execute_single_tool(tc, tool_map, change_tracker)

    timings: dict[str, float] = {}
    messages: list[Message] = []

    if parallel:
        results = await asyncio.gather(*[execute_and_message(tc) for tc in tool_calls])
        for tc, (msg, elapsed) in zip(tool_calls, results):
            messages.append(msg)
            timings[tc.id] = elapsed
    else:
        for tc in tool_calls:
            msg, elapsed = await execute_and_message(tc)
            messages.append(msg)
            timings[tc.id] = elapsed

    return messages, timings


def create_tool_result_notice(tool_messages: list[Message]) -> Message | None:
    """Create a system notice message about tool execution results."""
    if not tool_messages:
        return None

    tool_results = "\n".join(
        f"Tool '{msg.tool_name}' returned: {msg.content[:200]}"
        for msg in tool_messages
        if msg.content
    )
    return Message(
        role="user",
        content=f"System Note: Tools executed.\n{tool_results}\n\nProvide a final response to the user summarizing these results.",
    )
