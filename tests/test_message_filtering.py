import pytest
from src.agentframework.web_api import filter_messages_for_ui

def test_filter_messages_for_ui():
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "assistant", "content": "System Note: Tools executed.\nTool 'search' returned: result"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "name": "search", "arguments": "{}"}]},
        {"role": "assistant", "content": "System Note: Tools executed.", "tool_calls": [{"id": "2", "name": "bash", "arguments": "{}"}]},
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

    # 5. Assistant message with "System Note" content but NO tools should be SKIPPED
    # Wait, in the input 'messages', message at index 3 is this case.
    for m in filtered:
        if "System Note" in m["content"] and not m["has_tools"]:
             pytest.fail("Assistant message with System Note and no tools should be filtered out")

    # 6. Assistant message with tools and NO content should be PRESENT
    empty_with_tools = [m for m in filtered if m["has_tools"] and not m["content"] and m["role"] == "assistant"]
    assert len(empty_with_tools) == 1
    assert empty_with_tools[0]["has_tools"] is True

    # 7. Assistant message with tools and "System Note" content should be PRESENT
    sys_note_with_tools = [m for m in filtered if m["has_tools"] and "System Note" in m["content"]]
    # Note: my refactor keeps the content if has_tools is True
    assert len(sys_note_with_tools) == 1
    assert sys_note_with_tools[0]["has_tools"] is True

    # 8. Thinking extraction should work
    thinking_msg = [m for m in filtered if "thinking" in m]
    assert len(thinking_msg) == 1
    assert thinking_msg[0]["thinking"] == "Searching..."
    assert thinking_msg[0]["content"] == "Result is 42"

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
        Msg("assistant", "System Note: Tools executed", tool_calls=[{"id": "4"}]),
    ]

    filtered = filter_messages_for_ui(messages)
    assert len(filtered) == 3
    assert filtered[1]["has_tools"] is True
    assert filtered[2]["has_tools"] is True
