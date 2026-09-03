//! Tool system: the `Tool` trait contract, execution context, and the
//! registry of built-in tools.
//!
//! Tools never touch safety policy themselves beyond the checks the
//! context provides — approval gating is the agent loop's job (Phase 4);
//! the context carries everything a tool may need: safety policy,
//! config, session store, change tracker, ask-user callback, and the
//! shared HTTP client.
//!
//! Depends on: crate `config`, `error`, `safety`, `session`,
//! `change_tracker`, `llm::http`, `tokio`.

pub mod fs;
pub mod git;
pub mod knowledge;
pub mod misc;
pub mod network;
pub mod process;
pub mod registry;
pub mod research;
pub mod search;
pub mod semantic;
pub mod shell;
pub mod tool;
