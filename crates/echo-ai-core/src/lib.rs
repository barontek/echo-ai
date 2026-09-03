//! Echo AI core: the engine behind the web server and TUI.
//!
//! Owns the agent loop, LLM providers, tool registry, session store,
//! safety enforcement, config, and shared utilities — everything that is
//! not tied to a specific frontend (HTTP or terminal). Mirrors the C
//! project's subsystem split (`~/echo-ai-c/src/`), but is an idiomatic
//! rewrite, not a line-by-line port: only the on-disk formats (session
//! DB schema, Fernet token layout, config surface) are kept compatible.
//!
//! Depends on: `serde`/`serde_json`/`toml`, `rusqlite`, `RustCrypto`
//! crates, `tokio`.

// Lint policy (AGENTS.md "Error handling"): library code never unwraps or
// expects on a `Result`/`Option`; test code may. `panic!` is reserved for
// genuine programmer-error invariant violations.
#![cfg_attr(
    not(test),
    deny(clippy::unwrap_used, clippy::expect_used, clippy::panic)
)]
// TODO(multiple_crate_versions): hashbrown 0.14/0.17 (rusqlite→hashlink
// vs toml→indexmap) and syn 2/3 (proc-macro generations) are unavoidable
// transitive pairs; `cargo deny` reports them at warn (deny.toml) and the
// review doc records the exception.
#![allow(clippy::multiple_crate_versions)]

pub mod agent;
pub mod browser;
pub mod change_tracker;
pub mod config;
pub mod error;
pub mod llm;
pub mod safety;
pub mod session;
pub mod tools;
pub mod utils;

pub use error::{Error, Result};
