//! Agent subsystem: the conversation loop and its data model.
//!
//! `message.rs` (the model) lands in Phase 1 because the session store
//! persists it; the run loop, prompt building, title generation, and
//! context windowing land in Phase 4.
//!
//! Depends on: `serde`.

pub mod message;
