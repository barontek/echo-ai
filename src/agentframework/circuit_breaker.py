"""Circuit breaker pattern for resilient provider calls."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""

    failure_threshold: int = 5
    success_threshold: int = 2
    timeout: float = 30.0
    half_open_max_calls: int = 3


@dataclass
class CircuitBreaker:
    """Circuit breaker for provider calls.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Too many failures, requests are rejected immediately
    - HALF_OPEN: Testing if service recovered, limited requests allowed
    """

    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    state: CircuitState = field(default=CircuitState.CLOSED)
    failure_count: int = field(default=0)
    success_count: int = field(default=0)
    last_failure_time: float = field(default=0)
    half_open_calls: int = field(default=0)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    def _should_attempt(self) -> bool:
        """Check if a request should be attempted."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.config.timeout:
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
                logger.info("Circuit breaker transitioning to HALF_OPEN")
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_calls < self.config.half_open_max_calls:
                self.half_open_calls += 1
                return True
            return False

        return False

    def _record_success(self) -> None:
        """Record a successful call."""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.half_open_calls > 0:
                self.half_open_calls -= 1
            if self.success_count >= self.config.success_threshold:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
                logger.info("Circuit breaker CLOSED after successful recovery")
        else:
            self.failure_count = 0
            self.success_count = 0

    def _record_failure(self) -> None:
        """Record a failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_calls > 0:
                self.half_open_calls -= 1
            self.state = CircuitState.OPEN
            self.success_count = 0
            logger.warning("Circuit breaker OPEN after half-open failure")
        elif self.failure_count >= self.config.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning("Circuit breaker OPEN after %s failures", self.failure_count)

    async def call(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute a function with circuit breaker protection."""
        async with self._lock:
            if not self._should_attempt():
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is {self.state.value}, request rejected"
                )

        try:
            result = func(*args, **kwargs)
            if hasattr(result, "__await__"):
                result = await result
            async with self._lock:
                self._record_success()
            return result
        except Exception as e:
            async with self._lock:
                self._record_failure()
            raise

    def reset(self) -> None:
        """Reset the circuit breaker to closed state."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.half_open_calls = 0
        logger.info("Circuit breaker manually reset")


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and request is rejected."""

    pass


class CircuitBreakerWrapper:
    """Wraps an LLM provider with circuit breaker protection."""

    def __init__(self, provider: Any, config: CircuitBreakerConfig | None = None):
        self.provider = provider
        self.circuit_breaker = CircuitBreaker(config=config or CircuitBreakerConfig())

    async def chat(self, *args: Any, **kwargs: Any) -> Any:
        """Chat with circuit breaker protection."""
        return await self.circuit_breaker.call(self.provider.chat, *args, **kwargs)

    async def chat_streaming(self, *args: Any, **kwargs: Any) -> Any:
        """Streaming chat with circuit breaker protection."""
        return await self.circuit_breaker.call(
            self.provider.chat_streaming, *args, **kwargs
        )

    async def extract_structured(self, *args: Any, **kwargs: Any) -> Any:
        """Extract structured with circuit breaker protection."""
        return await self.circuit_breaker.call(
            self.provider.extract_structured, *args, **kwargs
        )

    def reset(self) -> None:
        """Reset the circuit breaker."""
        self.circuit_breaker.reset()
