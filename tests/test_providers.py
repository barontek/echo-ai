"""Tests for LLM providers."""

import json
import pytest
import respx
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from agentframework.providers.anthropic import AnthropicProvider
from agentframework.providers.openai import OpenAIProvider
from agentframework.providers.ollama import OllamaProvider


@pytest.mark.asyncio
async def test_openai_chat():
    with patch("agentframework.providers.openai.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_openai.return_value.__aenter__.return_value = mock_client
        mock_response = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.content = "OpenAI Response"
        mock_msg.tool_calls = None
        mock_response.choices = [MagicMock(message=mock_msg)]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        provider = OpenAIProvider(model="gpt-4", api_key="test-key")
        resp = await provider.chat([{"role": "user", "content": "hi"}])
        assert resp.content == "OpenAI Response"
        assert not resp.tool_calls


@pytest.mark.asyncio
async def test_anthropic_chat():
    with patch("agentframework.providers.anthropic.AsyncAnthropic") as mock_anth:
        mock_client = AsyncMock()
        mock_anth.return_value.__aenter__.return_value = mock_client
        mock_response = AsyncMock()

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Anthropic Response"

        mock_response.content = [text_block]
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        provider = AnthropicProvider(model="claude-3", api_key="test-key")
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
        resp = await provider.chat(messages)
        assert resp.content == "Anthropic Response"
        assert not resp.tool_calls


@pytest.mark.asyncio
@respx.mock
async def test_ollama_chat():
    provider = OllamaProvider(model="llama3")

    respx.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "Ollama Response",
                }
            }
        )
    )

    resp = await provider.chat([{"role": "user", "content": "hi"}])
    assert resp.content == "Ollama Response"
    assert not resp.tool_calls


@pytest.mark.asyncio
async def test_ollama_chat_streaming():
    with patch("agentframework.providers.ollama.httpx.AsyncClient") as mock_httpx:
        mock_client = AsyncMock()
        mock_httpx.return_value = mock_client

        class MockResponse:
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
            def raise_for_status(self):
                pass
            async def aiter_lines(self):
                yield json.dumps({"message": {"content": "Stream "}})
                yield json.dumps({"message": {"content": "Chunk "}})
                yield json.dumps({"message": {"content": "Finished"}, "done": True})

        mock_client.stream = MagicMock(return_value=MockResponse())

        provider = OllamaProvider(model="qwen3:4b-instruct") # Triggers streaming

        chunks = []
        def on_chunk(c):
            chunks.append(c)

        resp = await provider.chat_streaming([{"role": "user", "content": "hi"}], on_chunk=on_chunk)
        assert resp.content == "Stream Chunk Finished"
        assert chunks == ["Stream ", "Chunk ", "Finished"]

@pytest.mark.asyncio
async def test_openai_chat_streaming():
    with patch("agentframework.providers.openai.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_openai.return_value.__aenter__.return_value = mock_client

        class MockStream:
            def __init__(self):
                self._events = [
                    MagicMock(type="content.delta", delta="Stream"),
                    MagicMock(type="content.delta", delta=" Chunk"),
                ]

            def __aiter__(self):
                return self._gen()

            async def _gen(self):
                for e in self._events:
                    yield e

            async def get_final_completion(self):
                msg = MagicMock()
                msg.content = "Stream Chunk"
                msg.tool_calls = None
                choice = MagicMock()
                choice.message = msg
                completion = MagicMock()
                completion.choices = [choice]
                return completion

        class MockStreamManager:
            async def __aenter__(self):
                return MockStream()
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        mock_client.chat.completions.stream = MagicMock(return_value=MockStreamManager())

        provider = OpenAIProvider(model="gpt-4", api_key="test-key")
        chunks = []
        resp = await provider.chat_streaming([{"role": "user", "content": "hi"}], on_chunk=chunks.append)

        assert resp.content == "Stream Chunk"
        assert chunks == ["Stream", " Chunk"]

@pytest.mark.asyncio
async def test_anthropic_chat_streaming():
    with patch("agentframework.providers.anthropic.AsyncAnthropic") as mock_anth:
        mock_client = AsyncMock()
        mock_anth.return_value.__aenter__.return_value = mock_client

        class MockStream:
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
            @property
            def text_stream(self):
                async def _gen():
                    yield "Stream"
                    yield " Chunk"
                return _gen()
            async def get_final_message(self):
                msg = MagicMock()
                msg.content = []
                return msg

        mock_client.messages.stream = MagicMock(return_value=MockStream())

        provider = AnthropicProvider(model="claude-3", api_key="test-key")
        chunks = []
        resp = await provider.chat_streaming([{"role": "user", "content": "hi"}], on_chunk=chunks.append)

        assert resp.content == "Stream Chunk"
        assert chunks == ["Stream", " Chunk"]
