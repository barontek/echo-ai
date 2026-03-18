import pytest
import json
from unittest.mock import MagicMock, patch, AsyncMock
from src.agentframework.providers.ollama import OllamaProvider

@pytest.fixture
def provider():
    return OllamaProvider(model="test-model")

def test_extract_tool_calls_markdown(provider):
    content = "Here is a tool call:\n```json\n{\"name\": \"test_tool\", \"arguments\": {\"arg\": 1}}\n```"
    calls = provider._extract_tool_calls_from_content(content)
    assert len(calls) == 1
    assert calls[0].name == "test_tool"
    assert calls[0].arguments == {"arg": 1}

def test_extract_tool_calls_plain_json(provider):
    content = 'Some text {"name": "test_tool", "arguments": {"arg": 1}} more text'
    calls = provider._extract_tool_calls_from_content(content)
    assert len(calls) == 1
    assert calls[0].name == "test_tool"
    assert calls[0].arguments == {"arg": 1}

def test_extract_tool_calls_invalid(provider):
    content = "```json\n{invalid}\n```"
    calls = provider._extract_tool_calls_from_content(content)
    assert len(calls) == 0

@pytest.mark.asyncio
async def test_ollama_chat_streaming_success(provider):
    # Mock httpx client stream
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    async def mock_aiter_lines():
        chunks = [
            {"message": {"thinking": "Logic step 1\n"}},
            {"message": {"thinking": "Logic step 2\n"}},
            {"message": {"content": "The result "}},
            {"message": {"content": "is 42"}},
            {"done": True}
        ]
        for chunk in chunks:
            yield json.dumps(chunk)

    mock_response.aiter_lines = mock_aiter_lines

    # We need to mock the context manager __aenter__
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_response

    provider.client.stream = MagicMock(return_value=mock_cm)

    chunks_received = []
    def on_chunk(c):
        chunks_received.append(c)

    response = await provider.chat_streaming([{"role": "user", "content": "hi"}], on_chunk=on_chunk)

    assert "__THINKING__" in chunks_received
    assert "Logic step 1\n" in chunks_received
    assert "__THINKING_END__" in chunks_received
    assert "The result " in chunks_received
    assert "is 42" in chunks_received
    assert response.content == "The result is 42"

@pytest.mark.asyncio
async def test_ollama_chat_streaming_tool_call(provider):
    provider.model = "qwen3" # Trigger reasoning streaming path
    async def mock_aiter_lines():
        chunks = [
            {"message": {"content": "```json\n"}},
            {"message": {"content": "{\"name\": \"get_weather\", \"arguments\": {\"city\": \"London\"}}\n"}},
            {"message": {"content": "```"}},
            {"done": True}
        ]
        for chunk in chunks:
            yield json.dumps(chunk)

    mock_response = MagicMock()
    mock_response.aiter_lines = mock_aiter_lines
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_response
    provider.client.stream = MagicMock(return_value=mock_cm)

    response = await provider.chat_streaming(
        [{"role": "user", "content": "weather?"}],
        tools=[{"type": "function", "function": {"name": "get_weather"}}]
    )

    print(f"DEBUG: Response content: {repr(response.content)}")
    print(f"DEBUG: Response tool calls: {response.tool_calls}")

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "get_weather"
    assert response.tool_calls[0].arguments == {"city": "London"}
    assert response.content == ""

def test_ollama_list_models(provider):
    with patch("httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"models": [{"name": "m1"}, {"name": "m2"}]}
        mock_get.return_value = mock_resp

        models = provider.list_models()
        assert models == ["m1", "m2"]
