"""Logging utilities for plain and structured debug output."""

from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar
from typing import Any


# Context variable for correlation/request IDs
correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str:
    """Get the current correlation ID or generate a new one."""
    cid = correlation_id.get()
    if cid is None:
        cid = str(uuid.uuid4())[:8]
        correlation_id.set(cid)
    return cid


def set_correlation_id(cid: str | None) -> None:
    """Set the correlation ID for the current context."""
    correlation_id.set(cid)


class CorrelationIdFilter(logging.Filter):
    """Filter that adds correlation_id to log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


class JsonFormatter(logging.Formatter):
    """Simple JSON formatter for structured debug logs."""

    RESERVED = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "correlation_id",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "timestamp": self.formatTime(record),
        }
        for key, value in record.__dict__.items():
            if key not in self.RESERVED and not key.startswith("_"):
                payload[key] = value

        # Include OpenTelemetry trace ID if active
        try:
            from opentelemetry import trace

            span = trace.get_current_span()
            if span and span.get_span_context().is_valid:
                trace_id = span.get_span_context().trace_id
                payload["trace_id"] = format(trace_id, "032x")
        except ImportError:
            pass

        # Include exception info if present
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(debug_enabled: bool, debug_json: bool = False) -> None:
    """Configure logger for debug or regular operation."""
    if not debug_enabled:
        return

    handler = logging.StreamHandler()
    handler.addFilter(CorrelationIdFilter())

    if debug_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(correlation_id)s] %(levelname)s %(name)s %(message)s"
            )
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
