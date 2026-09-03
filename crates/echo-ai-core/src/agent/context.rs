//! Context windowing: trimming the conversation to fit the model's
//! budget, and transcript summarization.
//!
//! The C version's `context.c` (smart selection, thinking splitting)
//! reduces to two simple rules here: keep the system prompt + the most
//! recent messages up to the budgets, and when even that overflows,
//! summarize the head into a compressed replacement.
//!
//! Depends on: crate `llm::provider`.

use crate::llm::provider::LlmMessage;

/// Trims a conversation to `max_messages` / `max_chars` budgets.
///
/// The system message (role `system`) is always kept at the front; the
/// trimmed head is replaced by a single `assistant` note.
#[must_use]
pub fn trim_context(
    messages: Vec<LlmMessage>,
    max_messages: usize,
    max_chars: usize,
) -> Vec<LlmMessage> {
    let mut messages = messages;
    let mut trimmed_head = false;

    // Cut by message count (keep the tail).
    if messages.len() > max_messages.max(1) {
        let split = messages.len() - max_messages.max(1);
        messages.drain(..split);
        trimmed_head = true;
    }

    // Cut by character budget (keep the tail).
    let total: usize = messages.iter().map(|m| m.content.len()).sum();
    if total > max_chars {
        let mut kept = 0usize;
        let mut split = 0usize;
        for (i, m) in messages.iter().enumerate() {
            kept += m.content.len();
            if kept > max_chars {
                split = i;
                break;
            }
        }
        if split > 0 {
            messages.drain(..split);
            trimmed_head = true;
        }
    }

    if trimmed_head {
        messages.insert(
            0,
            LlmMessage {
                role: String::from("assistant"),
                content: String::from("[earlier conversation trimmed to fit the context window]"),
                tool_calls: Vec::new(),
                tool_call_id: None,
            },
        );
    }
    messages
}

/// Builds a summarization request for the transcript head.
#[must_use]
pub fn summarize_prompt(transcript: &[LlmMessage], max_chars: usize) -> String {
    use std::fmt::Write as _;
    let mut text = String::new();
    for m in transcript.iter().take(40) {
        let _ = writeln!(text, "[{}] {}", m.role, m.content);
        if text.len() > max_chars {
            break;
        }
    }
    format!(
        "Summarize the conversation so far in a few sentences, preserving \
         decisions, user preferences, and open questions. The summary will \
         replace the conversation history.\n\n{text}"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn msg(role: &str, content: impl Into<String>) -> LlmMessage {
        LlmMessage {
            role: String::from(role),
            content: content.into(),
            tool_calls: Vec::new(),
            tool_call_id: None,
        }
    }

    #[test]
    fn trims_by_message_count_keeping_tail() {
        let msgs: Vec<LlmMessage> = (0..10).map(|i| msg("user", format!("m{i}"))).collect();
        let out = trim_context(msgs, 3, usize::MAX);
        assert_eq!(out.len(), 4, "3 kept + 1 trim note");
        assert!(out[0].content.contains("trimmed"));
        assert!(out.last().unwrap().content.contains("m9"));
    }

    #[test]
    fn trims_by_character_budget() {
        let msgs = vec![
            msg("user", "a".repeat(100)),
            msg("assistant", "b".repeat(100)),
            msg("user", "c".repeat(100)),
        ];
        let out = trim_context(msgs, usize::MAX, 150);
        assert!(out.len() <= 3, "char trim keeps tail only");
        assert!(out.last().unwrap().content.contains('c'));
    }

    #[test]
    fn no_trim_when_within_budget() {
        let msgs = vec![msg("user", "hi"), msg("assistant", "hello")];
        let out = trim_context(msgs.clone(), 100, 10_000);
        assert_eq!(out, msgs);
    }

    #[test]
    fn summarize_prompt_contains_transcript() {
        let msgs = vec![msg("user", "hello there")];
        let prompt = summarize_prompt(&msgs, 10_000);
        assert!(prompt.contains("hello there"));
        assert!(prompt.contains("decisions"));
    }
}
