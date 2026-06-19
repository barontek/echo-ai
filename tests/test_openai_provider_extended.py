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


def _make_mock_event(event_type: str, **kwargs):
    event = MagicMock()
    event.type = event_type
    for k, v in kwargs.items():
        setattr(event, k, v)
    return event


def _make_mock_completion(content: str | None, tool_calls: list | None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    choice = MagicMock()
    choice.message = msg
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _make_mock_tool_call(id: str, name: str, arguments: str):
    tc = MagicMock()
    tc.id = id
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


def _make_mock_stream(events: list, completion):
    async def _aiter(_self=None):
        for event in events:
            yield event

    stream = AsyncMock()
    stream.__aiter__ = _aiter
    stream.get_final_completion = AsyncMock(return_value=completion)
    return stream


def _make_mock_stream_manager(stream):
    mgr = MagicMock()
    mgr.__aenter__ = AsyncMock(return_value=stream)
    mgr.__aexit__ = AsyncMock(return_value=None)
    return mgr


@pytest.fixture(autouse=True)
def _mock_openai_client():
    with patch("src.agentframework.providers.openai.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        # stream() is a sync method on AsyncCompletions, so use MagicMock
        mock_client.chat.completions.stream = MagicMock()
        mock_cls.return_value = mock_client
        yield mock_client


@pytest.mark.asyncio
async def test_openai_chat_streaming_text_content(provider, _mock_openai_client):
    events = [
        _make_mock_event("content.delta", delta="Hello"),
        _make_mock_event("content.delta", delta=" world"),
    ]
    completion = _make_mock_completion(content="Hello world", tool_calls=None)
    stream = _make_mock_stream(events, completion)
    stream_manager = _make_mock_stream_manager(stream)
    _mock_openai_client.chat.completions.stream.return_value = stream_manager

    chunks = []
    response = await provider.chat_streaming(
        [{"role": "user", "content": "hi"}],
        on_chunk=lambda c: chunks.append(c),
    )

    assert response.content == "Hello world"
    assert chunks == ["Hello", " world"]
    assert response.tool_calls == []


@pytest.mark.asyncio
async def test_openai_chat_streaming_tool_calls(provider, _mock_openai_client):
    events = [
        _make_mock_event("content.delta", delta=""),
    ]
    mock_tc = _make_mock_tool_call(
        id="call_abc123",
        name="get_weather",
        arguments=json.dumps({"city": "London"}),
    )
    completion = _make_mock_completion(content=None, tool_calls=[mock_tc])
    stream = _make_mock_stream(events, completion)
    stream_manager = _make_mock_stream_manager(stream)
    _mock_openai_client.chat.completions.stream.return_value = stream_manager

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
    events = [
        _make_mock_event("content.delta", delta="A"),
        _make_mock_event("content.delta", delta="B"),
        _make_mock_event("content.delta", delta="C"),
    ]
    completion = _make_mock_completion(content="ABC", tool_calls=None)
    stream = _make_mock_stream(events, completion)
    stream_manager = _make_mock_stream_manager(stream)
    _mock_openai_client.chat.completions.stream.return_value = stream_manager

    chunks = []
    response = await provider.chat_streaming(
        [{"role": "user", "content": "hi"}],
        on_chunk=lambda c: chunks.append(c),
    )

    assert chunks == ["A", "B", "C"]
    assert response.content == "ABC"


@pytest.mark.asyncio
async def test_openai_chat_streaming_empty_content(provider, _mock_openai_client):
    events: list = []
    mock_tc = _make_mock_tool_call(
        id="call_1",
        name="get_weather",
        arguments=json.dumps({"city": "Paris"}),
    )
    completion = _make_mock_completion(content=None, tool_calls=[mock_tc])
    stream = _make_mock_stream(events, completion)
    stream_manager = _make_mock_stream_manager(stream)
    _mock_openai_client.chat.completions.stream.return_value = stream_manager

    response = await provider.chat_streaming(
        [{"role": "user", "content": "weather?"}],
    )

    assert response.content == ""
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].arguments == {"city": "Paris"}


@pytest.mark.asyncio
async def test_openai_chat_streaming_malformed_json_args(provider, _mock_openai_client):
    events = [_make_mock_event("content.delta", delta="")]
    mock_tc = _make_mock_tool_call(
        id="call_bad",
        name="bad_tool",
        arguments="not valid json",
    )
    completion = _make_mock_completion(content=None, tool_calls=[mock_tc])
    stream = _make_mock_stream(events, completion)
    stream_manager = _make_mock_stream_manager(stream)
    _mock_openai_client.chat.completions.stream.return_value = stream_manager

    response = await provider.chat_streaming(
        [{"role": "user", "content": "do something"}],
    )

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "bad_tool"
    assert response.tool_calls[0].arguments == {}


@pytest.mark.asyncio
async def test_openai_chat_streaming_ignores_non_delta_events(provider, _mock_openai_client):
    events = [
        _make_mock_event("chunk"),
        _make_mock_event("refusal.delta", delta="no"),
        _make_mock_event("content.delta", delta="real"),
        _make_mock_event("tool_calls.function.arguments.done"),
    ]
    completion = _make_mock_completion(content="real", tool_calls=None)
    stream = _make_mock_stream(events, completion)
    stream_manager = _make_mock_stream_manager(stream)
    _mock_openai_client.chat.completions.stream.return_value = stream_manager

    chunks = []
    response = await provider.chat_streaming(
        [{"role": "user", "content": "hi"}],
        on_chunk=lambda c: chunks.append(c),
    )

    assert chunks == ["real"]
    assert response.content == "real"


@pytest.mark.asyncio
async def test_openai_chat_streaming_params_passed_correctly(provider, _mock_openai_client):
    events = [_make_mock_event("content.delta", delta="")]
    completion = _make_mock_completion(content="", tool_calls=None)
    stream = _make_mock_stream(events, completion)
    stream_manager = _make_mock_stream_manager(stream)
    _mock_openai_client.chat.completions.stream.return_value = stream_manager

    tools = [{"name": "test_tool"}]
    await provider.chat_streaming(
        [{"role": "user", "content": "hello"}],
        tools=tools,
        temperature=0.7,
    )

    _mock_openai_client.chat.completions.stream.assert_called_once()
    call_kwargs = _mock_openai_client.chat.completions.stream.call_args[1]
    assert call_kwargs["model"] == "gpt-4"
    assert call_kwargs["temperature"] == 0.7
    assert call_kwargs["tools"] == tools
    assert "stream" not in call_kwargs


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
