"""Tests for circuit breaker pattern."""

import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.agentframework.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitBreakerWrapper,
    CircuitState,
)


class TestCircuitBreakerConfig:
    def test_default_config(self):
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.success_threshold == 2
        assert config.timeout == 30.0
        assert config.half_open_max_calls == 3

    def test_custom_config(self):
        config = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=1,
            timeout=10.0,
            half_open_max_calls=1,
        )
        assert config.failure_threshold == 3
        assert config.success_threshold == 1
        assert config.timeout == 10.0
        assert config.half_open_max_calls == 1


class TestCircuitBreakerStates:
    def test_initial_state(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.success_count == 0

    def test_should_attempt_when_closed(self):
        cb = CircuitBreaker()
        assert cb._should_attempt() is True

    def test_open_rejects_requests(self):
        cb = CircuitBreaker(config=CircuitBreakerConfig(timeout=9999))
        cb.state = CircuitState.OPEN
        cb.last_failure_time = time.time()
        assert cb._should_attempt() is False

    def test_open_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(config=CircuitBreakerConfig(timeout=0))
        cb.state = CircuitState.OPEN
        cb.last_failure_time = time.time() - 1
        assert cb._should_attempt() is True
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.half_open_calls == 0

    def test_half_open_limits_calls(self):
        cb = CircuitBreaker(config=CircuitBreakerConfig(half_open_max_calls=2))
        cb.state = CircuitState.HALF_OPEN
        assert cb._should_attempt() is True
        assert cb._should_attempt() is True
        assert cb._should_attempt() is False

    def test_record_success_in_half_open(self):
        cb = CircuitBreaker(config=CircuitBreakerConfig(success_threshold=2))
        cb.state = CircuitState.HALF_OPEN
        cb._record_success()
        assert cb.success_count == 1
        assert cb.state == CircuitState.HALF_OPEN
        cb._record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.success_count == 0

    def test_record_success_in_closed_resets_failures(self):
        cb = CircuitBreaker()
        cb.failure_count = 3
        cb._record_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_record_failure_in_closed_opens_at_threshold(self):
        cb = CircuitBreaker(config=CircuitBreakerConfig(failure_threshold=3))
        cb._record_failure()
        assert cb.failure_count == 1
        assert cb.state == CircuitState.CLOSED
        cb._record_failure()
        assert cb.failure_count == 2
        assert cb.state == CircuitState.CLOSED
        cb._record_failure()
        assert cb.state == CircuitState.OPEN

    def test_record_failure_in_half_open_reopens(self):
        cb = CircuitBreaker()
        cb.state = CircuitState.HALF_OPEN
        cb._record_failure()
        assert cb.state == CircuitState.OPEN

    def test_record_failure_sets_last_failure_time(self):
        cb = CircuitBreaker()
        before = time.time()
        cb._record_failure()
        assert cb.last_failure_time >= before


class TestCircuitBreakerCall:
    @pytest.mark.asyncio
    async def test_sync_call_success(self):
        cb = CircuitBreaker()
        func = MagicMock(return_value="result")
        result = await cb.call(func)
        assert result == "result"
        func.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_call_failure(self):
        cb = CircuitBreaker()
        func = MagicMock(side_effect=ValueError("oops"))
        with pytest.raises(ValueError):
            await cb.call(func)
        assert cb.failure_count == 1

    @pytest.mark.asyncio
    async def test_async_call_success(self):
        cb = CircuitBreaker()
        func = AsyncMock(return_value="async_result")
        result = await cb.call(func)
        assert result == "async_result"

    @pytest.mark.asyncio
    async def test_async_call_failure(self):
        cb = CircuitBreaker()
        func = AsyncMock(side_effect=RuntimeError("fail"))
        with pytest.raises(RuntimeError):
            await cb.call(func)
        assert cb.failure_count == 1

    @pytest.mark.asyncio
    async def test_rejected_when_open(self):
        cb = CircuitBreaker(config=CircuitBreakerConfig(timeout=9999))
        cb.state = CircuitState.OPEN
        cb.last_failure_time = time.time()
        func = MagicMock()
        with pytest.raises(CircuitBreakerOpenError, match="open"):
            await cb.call(func)
        func.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejected_when_half_open_exhausted(self):
        cb = CircuitBreaker(config=CircuitBreakerConfig(half_open_max_calls=1))
        cb.state = CircuitState.HALF_OPEN
        cb.half_open_calls = 1
        func = MagicMock()
        with pytest.raises(CircuitBreakerOpenError, match="half_open"):
            await cb.call(func)
        func.assert_not_called()

    def test_reset(self):
        cb = CircuitBreaker()
        cb.state = CircuitState.OPEN
        cb.failure_count = 5
        cb.success_count = 2
        cb.half_open_calls = 1
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.success_count == 0
        assert cb.half_open_calls == 0


class TestCircuitBreakerWrapper:
    def test_wrapper_initialization(self):
        provider = MagicMock()
        wrapper = CircuitBreakerWrapper(provider)
        assert wrapper.provider is provider
        assert wrapper.circuit_breaker.state == CircuitState.CLOSED

    def test_wrapper_custom_config(self):
        provider = MagicMock()
        config = CircuitBreakerConfig(failure_threshold=3)
        wrapper = CircuitBreakerWrapper(provider, config=config)
        assert wrapper.circuit_breaker.config.failure_threshold == 3

    @pytest.mark.asyncio
    async def test_wrapper_chat(self):
        provider = MagicMock()
        provider.chat = AsyncMock(return_value="response")
        wrapper = CircuitBreakerWrapper(provider)
        result = await wrapper.chat("hello")
        assert result == "response"
        provider.chat.assert_called_once_with("hello")

    @pytest.mark.asyncio
    async def test_wrapper_chat_streaming(self):
        provider = MagicMock()
        provider.chat_streaming = AsyncMock(return_value="stream")
        wrapper = CircuitBreakerWrapper(provider)
        result = await wrapper.chat_streaming("hello")
        assert result == "stream"

    @pytest.mark.asyncio
    async def test_wrapper_extract_structured(self):
        provider = MagicMock()
        provider.extract_structured = AsyncMock(return_value={"key": "val"})
        wrapper = CircuitBreakerWrapper(provider)
        result = await wrapper.extract_structured("data")
        assert result == {"key": "val"}

    def test_wrapper_reset(self):
        provider = MagicMock()
        wrapper = CircuitBreakerWrapper(provider)
        wrapper.circuit_breaker.state = CircuitState.OPEN
        wrapper.reset()
        assert wrapper.circuit_breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_wrapper_rejects_when_open(self):
        provider = MagicMock()
        wrapper = CircuitBreakerWrapper(provider)
        wrapper.circuit_breaker.state = CircuitState.OPEN
        wrapper.circuit_breaker.config.timeout = 9999
        wrapper.circuit_breaker.last_failure_time = time.time()
        with pytest.raises(CircuitBreakerOpenError):
            await wrapper.chat("test")
        provider.chat.assert_not_called()


class TestCircuitBreakerOpenError:
    def test_error_is_exception(self):
        assert issubclass(CircuitBreakerOpenError, Exception)

    def test_error_message(self):
        err = CircuitBreakerOpenError("circuit is open")
        assert str(err) == "circuit is open"
