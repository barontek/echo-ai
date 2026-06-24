"""Extended tests for OpenAI provider."""

import json
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from src.agentframework.providers.openai import OpenAIProvider, _is_retryable_exception


def test_is_retryable_exception():
    assert _is_retryable_exception(Exception("Rate limit exceeded"))
    assert _is_retryable_exception(Exception("429 Too Many Requests"))
    assert _is_retryable_exception(Exception("Connection timeout"))
    assert not _is_retryable_exception(Exception("Syntax error"))


@pytest.fixture
def provider():
    return OpenAIProvider(model="gpt-4", api_key="sk-test")


def _make_chunk(content: str | None = None, tool_calls: list | None = None, choice: bool = True):
    """Create a mock ChatCompletionChunk."""
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = tool_calls
    delta.refusal = None
    choice_obj = MagicMock()
    choice_obj.delta = delta
    choice_obj.index = 0
    choice_obj.finish_reason = None
    chunk = MagicMock()
    chunk.choices = [choice_obj] if choice else []
    return chunk


def _make_tool_call_delta(
    index: int = 0,
    id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
):
    tc = MagicMock()
    tc.index = index
    tc.id = id
    if name is not None or arguments is not None:
        tc.function = MagicMock()
        tc.function.name = name
        tc.function.arguments = arguments
    else:
        tc.function = None
    return tc


def _make_async_iter(items):
    """Create an async iterator from a list."""
    async def _gen():
        for item in items:
            yield item
    return _gen()


@pytest.fixture(autouse=True)
def _mock_openai_client():
    with patch("src.agentframework.providers.openai.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock()
        mock_cls.return_value = mock_client
        yield mock_client


@pytest.mark.asyncio
async def test_openai_chat_streaming_text_content(provider, _mock_openai_client):
    chunks = [
        _make_chunk(content="Hello"),
        _make_chunk(content=" world"),
    ]
    _mock_openai_client.chat.completions.create.return_value = _make_async_iter(chunks)

    response_content = []
    response = await provider.chat_streaming(
        [{"role": "user", "content": "hi"}],
        on_chunk=lambda c: response_content.append(c),
    )

    assert response.content == "Hello world"
    assert response_content == ["Hello", " world"]
    assert response.tool_calls == []


@pytest.mark.asyncio
async def test_openai_chat_streaming_tool_calls(provider, _mock_openai_client):
    tc_delta = _make_tool_call_delta(
        index=0,
        id="call_abc123",
        name="get_weather",
        arguments=json.dumps({"city": "London"}),
    )
    chunks = [_make_chunk(content="", tool_calls=[tc_delta])]
    _mock_openai_client.chat.completions.create.return_value = _make_async_iter(chunks)

    response = await provider.chat_streaming(
        [{"role": "user", "content": "weather?"}],
        tools=[{"name": "get_weather"}],
    )

    assert response.content == ""
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "call_abc123"
    assert response.tool_calls[0].name == "get_weather"
    assert response.tool_calls[0].arguments == {"city": "London"}


@pytest.mark.asyncio
async def test_openai_chat_streaming_on_chunk_each_delta(provider, _mock_openai_client):
    chunks = [
        _make_chunk(content="A"),
        _make_chunk(content="B"),
        _make_chunk(content="C"),
    ]
    _mock_openai_client.chat.completions.create.return_value = _make_async_iter(chunks)

    response_chunks = []
    response = await provider.chat_streaming(
        [{"role": "user", "content": "hi"}],
        on_chunk=lambda c: response_chunks.append(c),
    )

    assert response_chunks == ["A", "B", "C"]
    assert response.content == "ABC"


@pytest.mark.asyncio
async def test_openai_chat_streaming_empty_content(provider, _mock_openai_client):
    tc_delta = _make_tool_call_delta(
        index=0,
        id="call_1",
        name="get_weather",
        arguments=json.dumps({"city": "Paris"}),
    )
    chunks = [_make_chunk(content=None, tool_calls=[tc_delta])]
    _mock_openai_client.chat.completions.create.return_value = _make_async_iter(chunks)

    response = await provider.chat_streaming(
        [{"role": "user", "content": "weather?"}],
    )

    assert response.content == ""
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].arguments == {"city": "Paris"}


@pytest.mark.asyncio
async def test_openai_chat_streaming_malformed_json_args(provider, _mock_openai_client):
    tc_delta = _make_tool_call_delta(
        index=0,
        id="call_bad",
        name="bad_tool",
        arguments="not valid json",
    )
    chunks = [_make_chunk(content="", tool_calls=[tc_delta])]
    _mock_openai_client.chat.completions.create.return_value = _make_async_iter(chunks)

    response = await provider.chat_streaming(
        [{"role": "user", "content": "do something"}],
    )

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "bad_tool"
    assert response.tool_calls[0].arguments == {"raw": "not valid json"}


@pytest.mark.asyncio
async def test_openai_chat_streaming_ignores_non_delta_events(provider, _mock_openai_client):
    # Chunks with no choices (e.g. usage chunks) should be ignored
    chunks = [
        _make_chunk(choice=False),
        _make_chunk(content="real"),
    ]
    _mock_openai_client.chat.completions.create.return_value = _make_async_iter(chunks)

    response_chunks = []
    response = await provider.chat_streaming(
        [{"role": "user", "content": "hi"}],
        on_chunk=lambda c: response_chunks.append(c),
    )

    assert response_chunks == ["real"]
    assert response.content == "real"


@pytest.mark.asyncio
async def test_openai_chat_streaming_params_passed_correctly(provider, _mock_openai_client):
    chunk = _make_chunk(content="")
    _mock_openai_client.chat.completions.create.return_value = _make_async_iter([chunk])

    tools = [{"name": "test_tool"}]
    await provider.chat_streaming(
        [{"role": "user", "content": "hello"}],
        tools=tools,
        temperature=0.7,
    )

    _mock_openai_client.chat.completions.create.assert_called_once()
    call_kwargs = _mock_openai_client.chat.completions.create.call_args[1]
    assert call_kwargs["model"] == "gpt-4"
    assert call_kwargs["temperature"] == 0.7
    assert call_kwargs["tools"] == tools
    assert call_kwargs["stream"] is True


@pytest.mark.asyncio
async def test_openai_extract_structured(provider, _mock_openai_client):
    class MockModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    with patch("instructor.from_openai") as mock_instructor_from_openai:
        mock_inst_client = MagicMock()
        mock_inst_client.chat.completions.create = AsyncMock(return_value=MockModel(result="success"))
        mock_instructor_from_openai.return_value = mock_inst_client

        res = await provider.extract_structured([{"role": "user", "content": "hi"}], MockModel)
        assert res.result == "success"
