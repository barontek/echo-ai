import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from src.agentframework.conversation import (
    Message,
    estimate_tokens,
    format_messages_for_llm,
    trim_messages_by_tokens,
    apply_context_window,
    summarize_old_messages,
    sanitize_json,
)


def test_estimate_tokens_fallback():
    import src.agentframework.conversation as conv_module

    conv_module._TIKTOKEN_ENCODER = None

    with patch("src.agentframework.conversation.tiktoken", create=True) as mock_tik:
        mock_tik.get_encoding.side_effect = Exception("failed")
        assert estimate_tokens("hello world") == 11 // 4


def test_format_messages_tool_calls_reconstruction():
    # Test reconstruction when tool_calls is missing but tool_call_id is present
    msg = Message(
        role="assistant",
        content="calling tool",
        tool_call_id="call_1",
        tool_name="search",
        tool_arguments={"q": "test"},
    )
    formatted = format_messages_for_llm([msg])
    # Expectation: formatted should have tool_calls populated
    assert "tool_calls" in formatted[1]  # [0] is system prompt
    assert formatted[1]["tool_calls"][0]["id"] == "call_1"


def test_trim_messages_max_tokens_zero():
    msgs = [Message(role="user", content="hi")]
    assert trim_messages_by_tokens(msgs, 0) == msgs


def test_trim_messages_tool_truncation():
    large_content = "x" * 15000
    msg = Message(role="tool", content=large_content, tool_call_id="1")
    trimmed = trim_messages_by_tokens([msg], 5000)
    assert "[Output truncated" in trimmed[0].content


def test_trim_messages_pull_user_context():
    # Logic to pull in user message if trimmed block starts with a tool message
    m_user = Message(role="user", content="user message")
    m_assistant = Message(role="assistant", content="thinking", tool_call_id="c1")
    m_tool = Message(role="tool", content="tool output", tool_call_id="c1")

    msgs = [m_user, m_assistant, m_tool]
    # Trim to only include the tool message (by token limit)
    # But it should pull in the user message if it detects it belongs to the same interaction
    trimmed = trim_messages_by_tokens(msgs, 5)  # Very small limit
    # This should trigger the block at line 150-159
    assert any(m.content == "user message" for m in trimmed)


@pytest.mark.asyncio
async def test_apply_context_window_no_limits():
    msgs = [Message(role="user", content="hi")]
    assert await apply_context_window(msgs, 0, 0) == msgs
    assert await apply_context_window([], 10, 100) == []


@pytest.mark.asyncio
async def test_apply_context_window_message_count_only():
    msgs = [Message(role="user", content=str(i)) for i in range(10)]
    result = await apply_context_window(msgs, 5, 0)
    assert len(result) == 5
    assert result[-1].content == "9"


@pytest.mark.asyncio
async def test_summarize_old_messages_formatting(mock_llm):
    msgs = [
        Message(role="user", content="my query"),
        Message(role="assistant", content="I will search", tool_name="search"),
        Message(role="tool", content="found stuff", tool_name="search"),
    ]
    mock_llm.chat.return_value = MagicMock(content="Summary result")
    summary = await summarize_old_messages(msgs, mock_llm)
    assert summary == "Summary result"

    # Check prompt formatting
    args, kwargs = mock_llm.chat.call_args
    prompt = kwargs["messages"][0]["content"]
    assert "User: my query" in prompt
    assert "Assistant used tool: search" in prompt
    assert "Tool search returned: found stuff" in prompt


@pytest.mark.asyncio
async def test_summarize_old_messages_truncation(mock_llm):
    # Extremely long conversation - need > 8000 tokens total in conversation_str
    # Individual messages are truncated to 500 chars (approx 125 tokens)
    # We need about 70-80 messages of 500 chars each.
    msgs = [Message(role="user", content="long message " * 100) for _ in range(100)]
    mock_llm.chat.return_value = MagicMock(content="Summary result")
    await summarize_old_messages(msgs, mock_llm)

    args, kwargs = mock_llm.chat.call_args
    prompt = kwargs["messages"][0]["content"]
    assert "[...conversation truncated" in prompt


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.chat = AsyncMock()
    return llm


def test_sanitize_json_variants():
    assert sanitize_json('```json\n{"a": 1}\n```').strip() == '{"a": 1}'
    assert sanitize_json('{"list": [1,2,],}').strip() == '{"list": [1,2]}'
