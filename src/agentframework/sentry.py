"""Sentry integration for Echo AI.

This module provides Sentry integration for error tracking and performance monitoring.
Uses lazy imports to avoid initializing Sentry until explicitly requested,
which prevents middleware conflicts with FastAPI and other ASGI frameworks.

Usage:
    from src.agentframework.sentry import captureException, init_sentry

    # Initialize only when needed (call once at app startup if SENTRY_DSN is set)
    init_sentry()

    # Or use directly - will auto-init on first use if DSN is set
    captureException(e)
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_sentry_initialized = False


def init_sentry() -> bool:
    """Initialize Sentry SDK if DSN is configured.

    Uses lazy imports to avoid auto-initialization that can cause
    middleware conflicts with FastAPI and other frameworks.

    Returns:
        True if Sentry was initialized, False otherwise.
    """
    global _sentry_initialized

    if _sentry_initialized:
        return True

    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        logger.debug("SENTRY_DSN not set, skipping Sentry initialization")
        return False

    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            send_default_pii=True,
            traces_sample_rate=1.0,
            environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
            release=f"echo-ai@{os.environ.get('SENTRY_RELEASE', '0.1.0')}",
        )

        _sentry_initialized = True
        logger.info(f"Sentry initialized with DSN: {dsn[:8]}...")
        return True
    except Exception as e:
        logger.warning(f"Failed to initialize Sentry: {e}")
        return False


def _ensure_sentry() -> Any:
    """Ensure Sentry SDK is initialized before use.

    Returns:
        The sentry_sdk module if initialized, None otherwise.
    """
    global _sentry_initialized
    if not _sentry_initialized:
        if not init_sentry():
            return None
    import sentry_sdk

    return sentry_sdk


def addBreadcrumb(
    category: str, message: str, level: str = "info", **kwargs: Any
) -> None:
    """Add a breadcrumb to the current transaction.

    Args:
        category: Category for the breadcrumb (e.g., 'http', 'database')
        message: Human-readable message
        level: Severity level (debug, info, warning, error, critical)
        **kwargs: Additional data to include
    """
    sdk = _ensure_sentry()
    if sdk is None:
        return
    breadcrumb: dict = {
        "category": category,
        "message": message,
        "level": level,
        **kwargs,
    }
    sdk.add_breadcrumb(breadcrumb)


def setUser(user_id: str, **kwargs: Any) -> None:
    """Set the current user for the transaction.

    Args:
        user_id: Unique identifier for the user
        **kwargs: Additional user data (email, username, ip_address)
    """
    sdk = _ensure_sentry()
    if sdk is None:
        return
    sdk.set_user({"id": user_id, **kwargs})


def captureException(
    exception: BaseException,
    extra: dict[str, Any] | None = None,
) -> None:
    """Capture an exception with optional additional context.

    Args:
        exception: The exception to capture
        extra: Optional dict of extra context data to attach to the event
    """
    sdk = _ensure_sentry()
    if sdk is None:
        logger.debug("Sentry not initialized, exception not captured: %s", exception)
        return

    if extra:
        with sdk.push_scope() as scope:
            for key, value in extra.items():
                scope.set_extra(key, value)
            sdk.capture_exception(exception)
    else:
        sdk.capture_exception(exception)


def captureMessage(message: str, level: str = "info", **kwargs: Any) -> None:
    """Capture a message with optional additional context.

    Args:
        message: The message to capture
        level: Severity level (debug, info, warning, error, critical)
        **kwargs: Additional context to include
    """
    sdk = _ensure_sentry()
    if sdk is None:
        return
    sdk.capture_message(message, level=level)


def startTransaction(name: str, op: str = "custom", **kwargs: Any) -> Any:
    """Start a new transaction for performance monitoring.

    Args:
        name: Name of the transaction
        op: Operation type (e.g., 'http.request', 'function.call')
        **kwargs: Additional transaction options

    Returns:
        Transaction context manager
    """
    sdk = _ensure_sentry()
    if sdk is None:
        return None
    return sdk.start_transaction(name=name, op=op, **kwargs)
