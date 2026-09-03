//! Echo AI core: the engine behind the web server and TUI.
//!
//! Owns the agent loop, LLM providers, tool registry, session store,
//! safety enforcement, config, and shared utilities — everything that is
//! not tied to a specific frontend (HTTP or terminal). Mirrors
//! `~/echo-ai-c/src/{agent,llm,tools,session,safety,config,change_tracker,utils}`.
//!
//! Depends on: `serde`/`serde_json`, `rusqlite`, `reqwest` (rustls),
//! `RustCrypto` crates, `tokio`.

// Lint policy (AGENTS.md "Error handling"): library code never unwraps or
// expects on a `Result`/`Option`; test code may. `panic!` is reserved for
// genuine programmer-error invariant violations.
#![cfg_attr(
    not(test),
    deny(clippy::unwrap_used, clippy::expect_used, clippy::panic)
)]
