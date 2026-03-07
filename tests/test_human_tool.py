import pytest
from unittest.mock import patch
from src.agentframework.tools.human import AskUserTool

@pytest.mark.asyncio
async def test_ask_user_tool_with_response():
    tool = AskUserTool()

    # Mock asyncio.to_thread to bypass blocking input
    with patch('asyncio.to_thread') as mock_thread:
        mock_thread.return_value = "Yes, proceed with the deletion."

        result = await tool.execute(question="Should I delete this file?")

        assert "Yes, proceed with the deletion" in result.content
        assert not result.error

@pytest.mark.asyncio
async def test_ask_user_tool_empty_response():
    tool = AskUserTool()

    with patch('asyncio.to_thread') as mock_thread:
        mock_thread.return_value = "   "

        result = await tool.execute(question="Should I continue?")

        assert "empty response" in result.content
        assert not result.error
