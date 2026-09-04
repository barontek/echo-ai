//! Echo AI TUI: the `--cli` terminal interface, ratatui + crossterm.
//!
//! The terminal UI:
//! worker-task agent execution, event ring, line editor, keymap/leader
//! chords, slash commands, dialogs, pickers, and the `CommonMark`
//! classifier. Pure UI models stay testable without a terminal (same
//! split the original implementation enforces between model and render).
//!
//! Depends on: `echo-ai-core`, `ratatui`, `crossterm`, `tokio`.

// Lint policy: see echo-ai-core/src/lib.rs.
#![cfg_attr(
    not(test),
    deny(clippy::unwrap_used, clippy::expect_used, clippy::panic)
)]
// TODO(multiple_crate_versions): hashbrown 0.14/0.17 (rusqlite vs toml
// indexmap) and syn 2/3 are unavoidable transitive pairs; `cargo deny`
// reports them at warn (deny.toml) and the review doc records the
// exception.
#![allow(clippy::multiple_crate_versions)]

pub mod app;
pub mod chat;
pub mod dialogs;
pub mod input;
pub mod keys;

use std::sync::Arc;

use echo_ai_core::agent::run::Agent;
use echo_ai_core::config::Config;

/// Runs the TUI.
///
/// # Errors
/// Terminal setup/teardown or agent-construction failures.
pub async fn run_tui(config: Config, agent: Option<Arc<Agent>>) -> Result<(), String> {
    let agent = match agent {
        Some(a) => a,
        None => app::build_agent(&config).map_err(|e| e.to_string())?,
    };
    app::run_tui(config, agent).await.map_err(|e| e.to_string())
}
