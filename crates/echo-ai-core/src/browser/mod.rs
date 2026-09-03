//! Browser subsystem: `CDP`-driven browser automation with stealth.
//!
//! `cdp.rs` is the transport (Chrome's `--remote-debugging-pipe` with
//! 4-byte LE framing), `stealth.rs` the fingerprint-reduction flags and
//! scripts, and `tools.rs` the tool implementations that share one
//! lazily-launched browser instance.
//!
//! Depends on: `tokio`, `libc`, `serde_json`, crate `tools`,
//! `utils::{html,string_utils}`.

pub mod cdp;
pub mod stealth;
pub mod tools;

pub use tools::BrowserManager;
