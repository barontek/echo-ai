from src.agentframework.web_api import filter_messages_for_ui

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
