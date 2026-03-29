"""Pytest bootstrap helpers for async test reliability."""

import asyncio
import inspect
from typing import Any

import pytest

from agentframework.providers import LLMResponse, LLMToolCall


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as async")


def pytest_pyfunc_call(pyfuncitem):
    """Run async tests even when pytest-asyncio is unavailable."""
    test_func = pyfuncitem.obj
    if inspect.iscoroutinefunction(test_func):
        sig = inspect.signature(test_func)
        kwargs = {
            name: pyfuncitem.funcargs[name]
            for name in sig.parameters
            if name in pyfuncitem.funcargs
        }
        asyncio.run(test_func(**kwargs))
        return True
    return None


@pytest.fixture
def mock_llm_provider():
    """Create a mock LLM provider for testing."""

    class MockLLMProvider:
        def __init__(self, responses: list[LLMResponse] | None = None):
            self.responses = responses or []
            self.response_index = 0
            self.call_count = 0
            self.last_messages = None

        async def chat(
            self,
            messages: list[dict[str, str]],
            tools: list[dict[str, Any]] | None = None,
            temperature: float = 0.3,
        ) -> LLMResponse:
            self.call_count += 1
            self.last_messages = messages
            if self.responses:
                response = self.responses[self.response_index % len(self.responses)]
                self.response_index += 1
                return response
            return LLMResponse(content="Mock response", tool_calls=[])

        async def chat_streaming(
            self,
            messages: list[dict[str, str]],
            tools: list[dict[str, Any]] | None = None,
            temperature: float = 0.3,
            on_chunk: Any = None,
        ) -> LLMResponse:
            response = await self.chat(messages, tools, temperature)
            if on_chunk:
                for char in response.content:
                    on_chunk(char)
            return response

        async def extract_structured(
            self,
            messages: list[dict[str, str]],
            response_model: type,
            temperature: float = 0.3,
        ) -> Any:
            return response_model()

    return MockLLMProvider


@pytest.fixture
def mock_llm_with_tools():
    """Create a mock LLM provider that returns tool calls."""

    def _create_mock(tools_to_return: list[str]):
        tool_calls = [
            LLMToolCall(
                id=f"call_{i}",
                name=tool_name,
                arguments={"query": "test"},
            )
            for i, tool_name in enumerate(tools_to_return)
        ]

        class MockProviderWithTools:
            async def chat(
                self,
                messages: list[dict[str, str]],
                tools: list[dict[str, Any]] | None = None,
                temperature: float = 0.3,
            ) -> LLMResponse:
                return LLMResponse(content="", tool_calls=tool_calls)

            async def extract_structured(
                self,
                messages: list[dict[str, str]],
                response_model: type,
                temperature: float = 0.3,
            ) -> Any:
                return response_model()

            async def chat_streaming(
                self,
                messages: list[dict[str, str]],
                tools: list[dict[str, Any]] | None = None,
                temperature: float = 0.3,
                on_chunk: Any = None,
            ) -> LLMResponse:
                return await self.chat(messages, tools, temperature)

        return MockProviderWithTools()

    return _create_mock


@pytest.fixture
def mock_llm_streaming():
    """Create a mock LLM provider that supports streaming."""

    class MockStreamingProvider:
        def __init__(self, response: str = "Streaming response"):
            self.response = response

        async def chat(
            self,
            messages: list[dict[str, str]],
            tools: list[dict[str, Any]] | None = None,
            temperature: float = 0.3,
        ) -> LLMResponse:
            return LLMResponse(content=self.response)

        async def chat_streaming(
            self,
            messages: list[dict[str, str]],
            tools: list[dict[str, Any]] | None = None,
            temperature: float = 0.3,
            on_chunk: Any = None,
        ) -> LLMResponse:
            for char in self.response:
                if on_chunk:
                    on_chunk(char)
                await asyncio.sleep(0)
            return LLMResponse(content=self.response)

        async def extract_structured(
            self,
            messages: list[dict[str, str]],
            response_model: type,
            temperature: float = 0.3,
        ) -> Any:
            return response_model()

    return MockStreamingProvider
