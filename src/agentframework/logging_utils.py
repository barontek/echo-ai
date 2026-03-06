"""Logging utilities for plain and structured debug output."""

from __future__ import annotations

import json
import logging


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
    }

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self.RESERVED:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(debug_enabled: bool, debug_json: bool = False) -> None:
    """Configure logger for debug or regular operation."""
    if not debug_enabled:
        return

    handler = logging.StreamHandler()
    if debug_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
