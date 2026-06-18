from src.agentframework.web_api import filter_messages_for_ui
from src.agentframework.web_utils import extract_thinking_content
from src.agentframework.constants import THINKING_START, THINKING_END


def test_extract_thinking_content():
    """Direct unit tests for the thinking extraction function."""
    # Normal case: both markers present
    thinking, display = extract_thinking_content("__THINKING__first_plan__THINKING_END__final_answer")
    assert thinking == "first_plan"
    assert display == "final_answer"

    # No thinking at all
    thinking, display = extract_thinking_content("just a plain message")
    assert thinking is None
    assert display == "just a plain message"

    # Unclosed thinking (no __THINKING_END__)
    thinking, display = extract_thinking_content("__THINKING__model started thinking but never closed it and kept going")
    assert thinking == "model started thinking but never closed it and kept going"
    assert display == ""

    # Only the opening marker (edge case)
    thinking, display = extract_thinking_content("__THINKING__")
    assert thinking == ""
    assert display == ""

    # Unclosed thinking with newlines
    content = f"{THINKING_START}\nmulti\nline\nthought\n{THINKING_END}\n\nanswer"
    thinking, display = extract_thinking_content(content)
    assert thinking == "multi\nline\nthought"
    assert display == "answer"


def test_filter_messages_for_ui():
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "name": "search", "arguments": "{}"}]},
        {"role": "tool", "content": "result", "tool_name": "search", "tool_call_id": "1"},
        {"role": "assistant", "content": "__THINKING__Searching...__THINKING_END__Result is 42"},
    ]

    filtered = filter_messages_for_ui(messages)

    # 1. System messages should be skipped
    assert not any(m["role"] == "system" for m in filtered)

    # 2. Tool messages should be skipped
    assert not any(m["role"] == "tool" for m in filtered)

    # 3. User message should be present
    assert filtered[0]["role"] == "user"
    assert filtered[0]["content"] == "Hello!"

    # 4. Normal assistant message should be present
    assert filtered[1]["role"] == "assistant"
    assert filtered[1]["content"] == "Hi there!"

    # 5. Assistant message with tools (no content) should be present
    assert filtered[2]["role"] == "assistant"
    assert filtered[2]["has_tools"] is True

    # 6. Thinking extraction should work
    thinking_msg = [m for m in filtered if "thinking" in m]
    assert len(thinking_msg) == 1
    assert thinking_msg[0]["thinking"] == "Searching..."
    assert thinking_msg[0]["content"] == "Result is 42"


def test_filter_messages_unclosed_thinking():
    """Session reload with unclosed __THINKING__ (model never output </think>)."""
    messages = [
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "__THINKING__The user wants a summary... I will use web_fetch..."},
    ]

    filtered = filter_messages_for_ui(messages)

    # The thinking content should be extracted, no raw __THINKING__ in display
    assert len(filtered) == 2
    thinking_msg = [m for m in filtered if "thinking" in m]
    assert len(thinking_msg) == 1
    # Everything after __THINKING__ becomes thinking content
    assert "The user wants a summary" in thinking_msg[0]["thinking"]
    # The display content should be empty (model never closed the tag)
    assert thinking_msg[0]["content"] == ""


def test_filter_messages_as_objects():
    class Msg:
        def __init__(self, role, content, tool_calls=None, timestamp="12:00"):
            self.role = role
            self.content = content
            self.tool_calls = tool_calls
            self.timestamp = timestamp

    messages = [
        Msg("assistant", "Normal"),
        Msg("assistant", "", tool_calls=[{"id": "3"}]),
    ]

    filtered = filter_messages_for_ui(messages)
    assert len(filtered) == 2
    assert filtered[1]["has_tools"] is True
