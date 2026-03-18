import pytest
import json
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, AsyncMock
from src.agentframework.api import app

@pytest.fixture
def client():
    return TestClient(app)

@pytest.mark.asyncio
async def test_stream_chat_success():
    # Use patch to mock get_or_create_agent
    with patch("src.agentframework.api.get_or_create_agent") as mock_get:
        mock_agent = MagicMock()

        async def mock_run_streaming(prompt, on_chunk):
            on_chunk("Hello")
            on_chunk(" world")
            return "Hello world"

        mock_agent.run_streaming = AsyncMock(side_effect=mock_run_streaming)
        mock_get.return_value = mock_agent

        # TestClient.get handles the async generator automatically if used correctly
        # or we can use httpx.AsyncClient for true async test
        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/stream", params={"prompt": "hi"})
            assert response.status_code == 200

            lines = []
            async for line in response.aiter_lines():
                if line.strip():
                    lines.append(line)

            assert len(lines) == 2
            assert json.loads(lines[0].replace("data: ", ""))["chunk"] == "Hello"
            assert json.loads(lines[1].replace("data: ", ""))["chunk"] == " world"

@pytest.mark.asyncio
async def test_stream_chat_agent_error():
    with patch("src.agentframework.api.get_or_create_agent") as mock_get:
        mock_agent = MagicMock()
        mock_agent.run_streaming = AsyncMock(side_effect=Exception("Stream failed"))
        mock_get.return_value = mock_agent

        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/stream", params={"prompt": "hi"})
            assert response.status_code == 200
            # The error happens in a background task, so we might just get an empty stream or disconnected
            # In the current implementation of stream_chat, chat_runner catches nothing and just closes the queue
            # Let's verify it closes cleanly
            async for _ in response.aiter_lines():
                pass
