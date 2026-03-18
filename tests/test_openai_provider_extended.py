import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from src.agentframework.providers.openai import OpenAIProvider, _is_retryable_exception

def test_is_retryable_exception():
    assert _is_retryable_exception(Exception("Rate limit exceeded"))
    assert _is_retryable_exception(Exception("429 Too Many Requests"))
    assert _is_retryable_exception(Exception("Connection timeout"))
    assert not _is_retryable_exception(Exception("Syntax error"))

@pytest.fixture
def provider():
    return OpenAIProvider(model="gpt-4", api_key="sk-test")

@pytest.mark.asyncio
async def test_openai_chat_streaming_success(provider):
    # Mock AsyncOpenAI client
    mock_choice = MagicMock()
    mock_choice.delta.content = "Hello"

    mock_chunk = MagicMock()
    mock_chunk.choices = [mock_choice]

    async def mock_aiter():
        yield mock_chunk
        # Second chunk with " world"
        c2 = MagicMock()
        c2.choices = [MagicMock(delta=MagicMock(content=" world"))]
        yield c2

    mock_response = MagicMock()
    mock_response.__aiter__ = lambda x: mock_aiter()

    with patch("src.agentframework.providers.openai.AsyncOpenAI") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response
        mock_client_cls.return_value = mock_client

        chunks = []
        def on_chunk(c):
            chunks.append(c)

        response = await provider.chat_streaming([{"role": "user", "content": "hi"}], on_chunk=on_chunk)

        assert response.content == "Hello world"
        assert chunks == ["Hello", " world"]

@pytest.mark.asyncio
async def test_openai_chat_streaming_tool_calls(provider):
    # Mock tool call chunks
    tc1 = MagicMock()
    tc1.index = 0
    tc1.id = "call_1"
    tc1.function.name = "get_weather"
    tc1.function.arguments = '{"city":'

    c1 = MagicMock(choices=[MagicMock(delta=MagicMock(content=None, tool_calls=[tc1]))])

    tc2 = MagicMock()
    tc2.index = 0
    tc2.id = None
    tc2.function.name = None
    tc2.function.arguments = '"London"}'

    c2 = MagicMock(choices=[MagicMock(delta=MagicMock(content=None, tool_calls=[tc2]))])

    async def mock_aiter():
        yield c1
        yield c2

    mock_response = MagicMock()
    mock_response.__aiter__ = lambda x: mock_aiter()

    with patch("src.agentframework.providers.openai.AsyncOpenAI") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response
        mock_client_cls.return_value = mock_client

        response = await provider.chat_streaming([{"role": "user", "content": "weather?"}], tools=[{"name": "get_weather"}])

        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "get_weather"
        assert response.tool_calls[0].arguments == {"city": "London"}

@pytest.mark.asyncio
async def test_openai_extract_structured(provider):
    class MockModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    with patch("src.agentframework.providers.openai.AsyncOpenAI") as mock_client_cls, \
         patch("instructor.from_openai") as mock_instructor_from_openai:

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        mock_inst_client = MagicMock()
        mock_inst_client.chat.completions.create = AsyncMock(return_value=MockModel(result="success"))
        mock_instructor_from_openai.return_value = mock_inst_client

        res = await provider.extract_structured([{"role": "user", "content": "hi"}], MockModel)
        assert res.result == "success"
