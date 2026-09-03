//! Message model: the unit of conversation, persisted by the session
//! store and exchanged with LLM providers.
//!
//! The JSON field names match the C project's `message.c` serialization
//! exactly (a session DB created by the C version must deserialize
//! cleanly here and vice versa). `serde` handles optionality: fields the
//! C version conditionally emits map to `Option<T>` with `skip_serializing_if`.
//!
//! Depends on: `serde`.

use serde::{Deserialize, Serialize};

/// A tool invocation attached to a message.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ToolCall {
    /// Provider-assigned call id.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    /// Always `"function"` in the current provider protocols.
    #[serde(default = "default_tool_type")]
    pub r#type: String,
    /// The function being invoked.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub function: Option<Function>,
    /// Result of executing the tool (filled in by the agent loop).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub result_content: Option<String>,
    /// Error message if the tool execution failed.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub result_error: Option<String>,
}

/// The `function` half of a [`ToolCall`].
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Function {
    /// Tool name, as registered in the tool registry.
    pub name: String,
    /// JSON-encoded arguments string (kept as a string so the model's
    /// exact text round-trips; the C version serialized it the same way).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub arguments: Option<String>,
}

/// One turn in a conversation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Message {
    /// Branching identity, present once a message has been persisted.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    /// Parent message in the branch tree.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_id: Option<String>,
    /// Identifies the fork group (regenerate/branch runs share one).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub fork_group_id: Option<String>,
    /// `system`, `user`, `assistant`, or `tool`.
    pub role: String,
    /// Text content; empty for pure tool-call messages.
    #[serde(default)]
    pub content: String,
    /// Reasoning text, kept separate from the visible content.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub thinking: Option<String>,
    /// Stream classifier phase at persistence time.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub phase: Option<String>,
    /// Provider-internal state (e.g. Codex phase tokens).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub provider_state: Option<String>,
    /// Tool invocations, for assistant messages.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tool_calls: Vec<ToolCall>,
    /// Which tool-call this message answers (tool messages only).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tool_call_id: Option<String>,
    /// Tool that produced this message (tool messages only).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tool_name: Option<String>,
    /// Machine-readable failure class for tool errors.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error_category: Option<String>,
    /// Unix epoch seconds when the message was created.
    #[serde(default)]
    pub timestamp: i64,
}

fn default_tool_type() -> String {
    String::from("function")
}

impl Message {
    /// A fresh user message with a timestamp.
    pub fn user(content: impl Into<String>) -> Self {
        Self {
            id: None,
            parent_id: None,
            fork_group_id: None,
            role: String::from("user"),
            content: content.into(),
            thinking: None,
            phase: None,
            provider_state: None,
            tool_calls: Vec::new(),
            tool_call_id: None,
            tool_name: None,
            error_category: None,
            timestamp: now_epoch_secs(),
        }
    }

    /// A fresh assistant message with a timestamp.
    pub fn assistant(content: impl Into<String>) -> Self {
        Self {
            id: None,
            parent_id: None,
            fork_group_id: None,
            role: String::from("assistant"),
            content: content.into(),
            thinking: None,
            phase: None,
            provider_state: None,
            tool_calls: Vec::new(),
            tool_call_id: None,
            tool_name: None,
            error_category: None,
            timestamp: now_epoch_secs(),
        }
    }
}

/// Unix epoch seconds; the C version used `time(NULL)` for the same field.
#[must_use]
pub fn now_epoch_secs() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(d) => i64::try_from(d.as_secs()).unwrap_or(i64::MAX),
        // Clock before the epoch: 0 is the C version's clamp value too.
        Err(_) => 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn user_message_roundtrips_through_json() {
        let m = Message::user("hello");
        let json = serde_json::to_string(&m).expect("serialize");
        let back: Message = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(m, back);
    }

    #[test]
    fn absent_optional_fields_are_skipped_in_json() {
        let m = Message::user("hello");
        let json = serde_json::to_string(&m).expect("serialize");
        assert!(!json.contains("thinking"), "unexpected field in {json}");
        assert!(!json.contains("tool_calls"), "unexpected field in {json}");
    }

    #[test]
    fn deserializes_c_style_message_without_optional_fields() {
        let c_json = r#"{"role":"assistant","content":"hi","timestamp":1750000000}"#;
        let m: Message = serde_json::from_str(c_json).expect("deserialize");
        assert_eq!(m.role, "assistant");
        assert_eq!(m.content, "hi");
        assert_eq!(m.timestamp, 1_750_000_000);
        assert!(m.tool_calls.is_empty());
    }

    #[test]
    fn tool_call_field_names_match_c_serialization() {
        let tc = ToolCall {
            id: Some(String::from("call_1")),
            r#type: String::from("function"),
            function: Some(Function {
                name: String::from("read_file"),
                arguments: Some(String::from(r#"{"path":"a.txt"}"#)),
            }),
            result_content: Some(String::from("file contents")),
            result_error: None,
        };
        let json = serde_json::to_string(&tc).expect("serialize");
        assert!(json.contains(r#""type":"function""#), "unexpected: {json}");
        assert!(json.contains(r#""arguments""#), "unexpected: {json}");
        assert!(json.contains(r#""result_content""#), "unexpected: {json}");
    }
}
