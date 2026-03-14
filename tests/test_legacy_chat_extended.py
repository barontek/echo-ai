import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from src.agentframework.chat import chat_session, strip_ansi
from src.agentframework.chat_runtime import (
    current_query_tool_messages,
    extract_urls,
    fetch_titles,
    get_input,
)
from src.agentframework.agent import Message

@pytest.mark.asyncio
async def test_get_input_fallback():
    with patch("src.agentframework.chat_runtime.prompt_session.prompt_async", side_effect=Exception("Prompt fail")), \
         patch("src.agentframework.chat_runtime.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.return_value = "user input"
        result = await get_input("?")
        assert result == "user input"
        mock_thread.assert_called()

def test_current_query_tool_messages():
    m1 = Message(role="user", content="hi")
    m2 = Message(role="assistant", content="hello")
    m3 = Message(role="user", content="how search works?")
    m4 = Message(role="tool", content="results", tool_name="web_search")
    m5 = Message(role="assistant", content="here they are")

    # Only 1 user message
    assert current_query_tool_messages([m1, m2]) == []

    # 2 user messages, tool in between
    messages = [m1, m2, m3, m4, m5]
    current_query_tool_messages(messages, tool_names={"web_search"})
    # It looks for tool messages BETWEEN the last two user messages or after the last one if only one exists?
    # Actually code says: candidates = messages[user_indexes[-2] + 1 : user_indexes[-1]]
    # This means messages BETWEEN user_indexes[-2] and user_indexes[-1].
    # Which are m1[0], m2[1], m3[2], m4[3], m5[4]
    # user_indexes = [0, 2]
    # candidates = messages[0+1 : 2] = [messages[1]] = [m2]
    # Wait, my logic is wrong? Let's check code:
    # 32: user_indexes = [i for i, message in enumerate(messages) if message.role == "user"]
    # 34: if len(user_indexes) >= 2:
    # 35:     candidates = messages[user_indexes[-2] + 1 : user_indexes[-1]]
    # That means messages between the PENULTIMATE user message and the LAST user message.

    m_user1 = Message(role="user", content="1")
    m_tool = Message(role="tool", content="t", tool_name="search")
    m_user2 = Message(role="user", content="2")

    assert current_query_tool_messages([m_user1, m_tool, m_user2]) == [m_tool]

def test_extract_urls():
    clean_response = "Check [Google](https://google.com) and (https://search.com)"
    tool_messages = [Message(role="tool", content="found https://bing.com", tool_name="search")]

    urls, cleaned = extract_urls(clean_response, tool_messages)

    assert ("Google", "https://google.com") in urls
    assert ("https://search.com", "https://search.com") in urls
    assert ("bing.com", "https://bing.com") in urls
    assert "google.com" not in cleaned
    assert "https" not in cleaned

@pytest.mark.asyncio
async def test_fetch_titles():
    url_pairs = [("site", "https://example.com")]

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value="<html><title>Example Domain</title></html>")

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_cm.__aexit__ = AsyncMock()

    mock_session = MagicMock()
    mock_session.get.return_value = mock_cm

    mock_session_cm = MagicMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock()

    with patch("aiohttp.ClientSession", return_value=mock_session_cm):
        titles = await fetch_titles(url_pairs)
        assert titles["https://example.com"] == "Example Domain"

@pytest.mark.asyncio
async def test_chat_session_with_thinking_and_sources():
    agent = MagicMock()

    async def mock_run_streaming(user_input, on_chunk):
        on_chunk("__THINKING__")
        on_chunk("thoughts")
        on_chunk("__THINKING_END__")
        on_chunk("response [Source](https://ext.com)")
        return "response [Source](https://ext.com)"

    agent.run_streaming = AsyncMock(side_effect=mock_run_streaming)
    agent.messages = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="resp", tool_calls=[{"id": "1"}]),
        Message(role="tool", content="tool out", tool_name="web_search", tool_call_id="1")
    ]

    with patch("src.agentframework.chat.get_input", side_effect=["hi", "/exit"]), \
         patch("src.agentframework.chat.execute_command", return_value=False), \
         patch("src.agentframework.chat.fetch_titles", AsyncMock(return_value={"https://ext.com": "Title"})), \
         patch("sys.stdout.write") as mock_write:
        await chat_session(agent)
        assert mock_write.called

def test_chat_main_entry():
    from src.agentframework.chat import main
    with patch("src.agentframework.chat.setup_agent"), \
         patch("src.agentframework.chat.asyncio.run") as mock_run:

        # Test interactive
        with patch("sys.argv", ["chat"]):
            main()
            assert mock_run.called

        # Test single run
        with patch("sys.argv", ["chat", "do something"]):
            main()
            assert mock_run.called

def test_strip_ansi():
    text = "\033[91mRed\033[0m Text"
    assert strip_ansi(text) == "Red Text"
