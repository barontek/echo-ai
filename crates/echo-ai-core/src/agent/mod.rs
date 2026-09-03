//! Agent subsystem: the conversation loop and its data model.
//!
//! `message.rs` is the persisted model; `agent.rs` is the LLM ↔ tool
//! loop with streaming events, approval gating, and title generation;
//! `context.rs` handles window trimming and summarization.
//!
//! Depends on: `tokio`, `tokio-util`, crate `llm`, `safety`, `tools`,
//! `session`, `change_tracker`.

pub mod context;
pub mod message;
pub mod run;
