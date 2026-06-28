"""Tool execution runtime helpers with structured error categories."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from time import perf_counter

from ..conversation import Message, sanitize_json
from ..providers import LLMToolCall
from ..session import ChangeTracker
from ..tools import Tool
from .callbacks import CallbackManager
from ..metrics import record_tool_execution

logger = logging.getLogger(__name__)


@dataclass
class ToolError:
    category: str
    message: str


ERROR_TEXT = {
    "validation_error": "Invalid arguments provided",
    "policy_denied": "Operation blocked by safety policy",
    "execution_error": "Tool execution failed",
    "timeout": "Tool execution timed out",
    "tool_not_found": "Tool not found in registry",
    "file_not_found": "File does not exist",
    "permission_denied": "Permission denied",
}


def format_tool_failure(error: ToolError) -> str:
    """Format a tool error into a user-friendly message."""
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
    callback_manager: CallbackManager | None = None,
    run_id: str = "",
) -> tuple[Message, float]:
    """Execute a single tool call and return the result message + duration seconds."""
    started = perf_counter()
    if callback_manager:
        callback_manager.on_tool_start(
            run_id, tool_call.name, getattr(tool_call, "arguments", {})
        )

    tool = tool_map.get(tool_call.name)
    if not tool:
        err = ToolError("tool_not_found", f"Unknown tool: {tool_call.name}")
        if callback_manager:
            callback_manager.on_tool_error(run_id, tool_call.name, str(err.message))
        record_tool_execution(tool_call.name, perf_counter() - started, False)
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
                err = ToolError(
                    "validation_error", f"Invalid JSON in arguments: {args}"
                )
                if callback_manager:
                    callback_manager.on_tool_error(
                        run_id, tool_call.name, "Invalid JSON in arguments"
                    )
                record_tool_execution(tool_call.name, perf_counter() - started, False)
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
            if callback_manager:
                callback_manager.on_tool_error(
                    run_id, tool_call.name, str(validation_error.message)
                )
            record_tool_execution(tool_call.name, perf_counter() - started, False)
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

        result = await tool.execute(**validated_args)  # type: ignore[arg-type]

        if change_tracker and result.metadata and "change" in result.metadata:
            change = result.metadata["change"]
            try:
                change_tracker.record_change(
                    change.get("action", "write"),
                    change.get("path"),
                    change.get("old_content"),
                    change.get("new_content"),
                    tool_call_id=tool_call.id,
                )
            except Exception as e:
                logger.debug("Failed to record change: %s", e)

        if result.error:
            if callback_manager:
                callback_manager.on_tool_error(run_id, tool_call.name, result.error)
            ec = result.error_category or "execution_error"
            msg = Message(
                role="tool",
                content=format_tool_failure(ToolError(ec, result.error)),
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                tool_arguments=tool_call.arguments,
                error_category=ec,
            )
            record_tool_execution(tool_call.name, perf_counter() - started, False)
        else:
            if callback_manager:
                callback_manager.on_tool_end(
                    run_id, tool_call.name, result.content or ""
                )
            msg = Message(
                role="tool",
                content=result.content or "",
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                tool_arguments=tool_call.arguments,
            )
            record_tool_execution(tool_call.name, perf_counter() - started, True)

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
        if callback_manager:
            callback_manager.on_tool_error(run_id, tool_call.name, str(err.message))
        record_tool_execution(tool_call.name, perf_counter() - started, False)
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
        if callback_manager:
            callback_manager.on_tool_error(run_id, tool_call.name, str(e))
        record_tool_execution(tool_call.name, perf_counter() - started, False)

        if change_tracker:
            reverted = change_tracker.revert_change_for_tool(tool_call.id)
            if reverted:
                logger.warning(
                    "Reverted %d changes for failed tool %s",
                    len(reverted),
                    tool_call.name,
                    extra={"tool_call_id": tool_call.id, "reverted_changes": reverted},
                )

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
    callback_manager: CallbackManager | None = None,
    run_id: str = "",
) -> tuple[list[Message], dict[str, float]]:
    """Execute tool calls and return result messages and timings by tool call id."""

    async def execute_and_message(tc: LLMToolCall):
        return await execute_single_tool(
            tc, tool_map, change_tracker, callback_manager, run_id
        )

    timings: dict[str, float] = {}
    messages: list[Message] = []

    if parallel:
        results = await asyncio.gather(
            *[execute_and_message(tc) for tc in tool_calls],
            return_exceptions=True,
        )
        for tc, result in zip(tool_calls, results):
            if isinstance(result, BaseException):
                logger.exception("Parallel tool %s failed: %s", tc.name, result)
                err_msg = f"Tool execution failed: {result}"
                messages.append(
                    Message(
                        role="tool",
                        content=err_msg,
                        tool_call_id=tc.id,
                        tool_name=tc.name,
                        tool_arguments=tc.arguments,
                        error_category="execution_error",
                    )
                )
                timings[tc.id] = 0.0
            else:
                msg, elapsed = result
                messages.append(msg)
                timings[tc.id] = elapsed
    else:
        for tc in tool_calls:
            msg, elapsed = await execute_and_message(tc)
            messages.append(msg)
            timings[tc.id] = elapsed

    return messages, timings
