//! Shared utilities: logging, metrics, circuit breaker, rate limiter,
//! string helpers, and the HTML-to-text pipeline.
//!
//! Mirrors the C project's `src/utils/` split (one responsibility per
//! module, no catch-all `utils.rs`); `callbacks` lands with the agent
//! (Phase 4) and `http_client` with the network tools (Phase 3).
//!
//! Depends on: crate `error`, `tokio` (rate limiter tests).

pub mod circuit_breaker;
pub mod logging;
pub mod metrics;
pub mod rate_limiter;
pub mod string_utils;
