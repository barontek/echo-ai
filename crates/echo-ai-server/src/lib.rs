//! Echo AI web server: `HTTPS`/`HTTP` + `WebSocket` frontend over axum.
//!
//! Replaces the C project's libuv server (`~/echo-ai-c/src/server/`):
//! axum routes (`REST` + `SSE` + `/ws/chat`), middleware (unlock token,
//! rate limiting, `CORS`), static frontend serving, and built-in `TLS` via
//! axum-server + rustls (self-signed localhost cert generated on first
//! run).
//!
//! Depends on: `echo-ai-core`, `tokio`, `axum`, `axum-server` (rustls),
//! `rcgen`, `tower-http`.

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
