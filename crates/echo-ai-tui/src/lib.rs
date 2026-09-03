//! Echo AI TUI: the `--cli` terminal interface, ratatui + crossterm.
//!
//! Replaces the C project's notcurses TUI (`~/echo-ai-c/src/tui/`):
//! worker-task agent execution, event ring, line editor, keymap/leader
//! chords, slash commands, dialogs, pickers, and the `CommonMark`
//! classifier. Pure UI models stay testable without a terminal (same
//! split the C version enforces between model and render).
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
