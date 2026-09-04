//! Echo AI web server: `HTTPS`/`HTTP` + `WebSocket` frontend over axum.
//!
//! Serves the web frontend and API over:
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

pub mod routes;
pub mod state;
pub mod tls;
pub mod ws;

use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;

use echo_ai_core::config::Config;
use echo_ai_core::session::SessionManager;

use crate::state::AppState;
use crate::tls::{TlsSettings, rustls_config, serve_plain, serve_tls};

/// Runs the server.
///
/// # Errors
/// `Error::Config` when the provider is invalid; `Error::Crypto` when
/// `TLS` setup fails; `Error::Session` on bind/serve failures.
pub async fn run_server(config: Config) -> echo_ai_core::Result<()> {
    let data_dir = default_data_dir();
    // Session store: open an existing vault, or create one only when a
    // password is provided (headless/`ECHO_AI_PASSWORD`). Without a
    // password on a fresh vault, the server starts in the setup state
    // and the web UI creates the vault with the submitted password.
    let session = if config.session.enabled {
        let password = std::env::var("ECHO_AI_PASSWORD").unwrap_or_default();
        let initialized = echo_ai_core::session::encryption::vault_initialized(&data_dir);
        if initialized {
            // An explicit password is authoritative for headless runs
            // (fail fast on mismatch); without one, start locked and
            // let the web UI's unlock screen verify and open the vault.
            if password.is_empty() {
                None
            } else {
                Some(Arc::new(SessionManager::open(&data_dir, &password)?))
            }
        } else if !password.is_empty() {
            // Fresh vault with a headless password: create it.
            Some(Arc::new(SessionManager::open(&data_dir, &password)?))
        } else {
            // Fresh vault, no password: the setup screen creates it.
            None
        }
    } else {
        None
    };
    let state = AppState::build(config.clone(), session, data_dir.clone())?;
    let frontend_dir = std::env::var("ECHO_AI_FRONTEND")
        .map_or_else(|_| PathBuf::from("frontend/dist"), PathBuf::from);

    let app = routes::router(state.clone(), frontend_dir);
    let addr = SocketAddr::new(
        config
            .server
            .bind
            .parse()
            .unwrap_or(std::net::IpAddr::V4(std::net::Ipv4Addr::LOCALHOST)),
        config.server.port,
    );

    let settings = TlsSettings::from(&config.server);
    if settings.enabled {
        let tls = rustls_config(&data_dir, &settings).await?;
        serve_tls(addr, tls, app).await
    } else {
        serve_plain(addr, app).await
    }
}

/// The default data directory (`~/.config/echo-ai`, compatible).
fn default_data_dir() -> PathBuf {
    std::env::var("ECHO_AI_DATA_DIR").map_or_else(
        |_| {
            let home = std::env::var("HOME").unwrap_or_else(|_| String::from("."));
            PathBuf::from(home).join(".config/echo-ai")
        },
        PathBuf::from,
    )
}
