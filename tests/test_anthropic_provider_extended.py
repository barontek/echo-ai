"""Extended tests for Anthropic provider - covering tool calls and edge cases."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.agentframework.providers.anthropic import AnthropicProvider


@pytest.mark.asyncio
async def test_anthropic_chat_with_tool_calls():
    with patch("src.agentframework.providers.anthropic.AsyncAnthropic") as mock_anth:
        mock_client = AsyncMock()
        mock_anth.return_value.__aenter__.return_value = mock_client
        mock_response = AsyncMock()

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Here is the result"

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "toolu_abc123"
        tool_block.name = "calculator"
        tool_block.input = {"a": 5, "b": 7}

        mock_response.content = [text_block, tool_block]
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        provider = AnthropicProvider(model="claude-3", api_key="test-key")
        messages = [{"role": "user", "content": "add 5 + 7"}]
        resp = await provider.chat(messages, tools=[{"name": "calculator", "input_schema": {"type": "object"}}])

        assert resp.content == "Here is the result"
        assert resp.tool_calls is not None
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].id == "toolu_abc123"
        assert resp.tool_calls[0].name == "calculator"
        assert resp.tool_calls[0].arguments == {"a": 5, "b": 7}


@pytest.mark.asyncio
async def test_anthropic_chat_streaming_with_tool_calls():
    with patch("src.agentframework.providers.anthropic.AsyncAnthropic") as mock_anth:
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
                    yield "Result"
                return _gen()
            async def get_final_message(self):
                msg = MagicMock()
                tool_block = MagicMock()
                tool_block.type = "tool_use"
                tool_block.id = "toolu_stream_1"
                tool_block.name = "search"
                tool_block.input = {"q": "test"}
                msg.content = [tool_block]
                return msg

        mock_client.messages.stream = MagicMock(return_value=MockStream())

        provider = AnthropicProvider(model="claude-3", api_key="test-key")
        chunks = []
        resp = await provider.chat_streaming(
            [{"role": "user", "content": "search"}],
            tools=[{"name": "search", "input_schema": {"type": "object"}}],
            on_chunk=chunks.append,
        )

        assert resp.tool_calls is not None
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "search"


@pytest.mark.asyncio
async def test_anthropic_chat_tools_param_passed():
    with patch("src.agentframework.providers.anthropic.AsyncAnthropic") as mock_anth:
        mock_client = AsyncMock()
        mock_anth.return_value.__aenter__.return_value = mock_client
        mock_response = AsyncMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "ok"
        mock_response.content = [text_block]
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        provider = AnthropicProvider(model="claude-3", api_key="test-key")
        await provider.chat(
            [{"role": "user", "content": "hi"}],
            tools=[{"name": "test_tool"}],
        )

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "tools" in call_kwargs
        assert call_kwargs["tools"] == [{"name": "test_tool"}]


@pytest.mark.asyncio
async def test_anthropic_chat_system_message():
    with patch("src.agentframework.providers.anthropic.AsyncAnthropic") as mock_anth:
        mock_client = AsyncMock()
        mock_anth.return_value.__aenter__.return_value = mock_client
        mock_response = AsyncMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "ok"
        mock_response.content = [text_block]
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        provider = AnthropicProvider(model="claude-3", api_key="test-key")
        await provider.chat(
            [{"role": "system", "content": "You are helpful"}, {"role": "user", "content": "hi"}]
        )

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "You are helpful"
        assert len(call_kwargs["messages"]) == 1
        assert call_kwargs["messages"][0]["role"] == "user"
