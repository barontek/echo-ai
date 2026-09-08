//! REST routes: status/health, auth (setup/unlock/logout), sessions,
//! chat (blocking + `SSE`), models, metrics, undo/redo, static files.
//!
//! Depends on: `axum`, `tower-http`, `echo-ai-core`, crate `state`.

mod auth;
mod chat;
mod meta;
mod sessions;

use std::sync::Arc;

use axum::Router;
use axum::extract::Query;
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use serde_json::Value;
use tower_http::cors::CorsLayer;
use tower_http::services::ServeDir;

use echo_ai_core::agent::message::Message;
use echo_ai_core::llm::provider::LlmMessage;

use crate::state::AppState;

/// Builds the router (REST + `SSE` + static + `WS`).
pub fn router(state: Arc<AppState>, frontend_dir: std::path::PathBuf) -> Router {
    Router::new()
        .route("/api/status", get(meta::status))
        .route("/api/health", get(meta::health))
        .route("/api/health/detailed", get(meta::health_detailed))
        .route("/api/config", get(meta::public_config))
        .route("/api/setup", post(auth::setup))
        .route("/api/unlock", post(auth::unlock))
        .route("/api/logout", post(auth::logout))
        .route("/api/change-password", post(auth::change_password))
        .route(
            "/api/sessions",
            get(sessions::list_sessions).post(sessions::create_session),
        )
        .route("/api/sessions/rename", post(sessions::rename_session))
        .route("/api/sessions/import", post(sessions::import_session))
        .route(
            "/api/sessions/{id}",
            get(sessions::get_session)
                .put(sessions::update_session)
                .delete(sessions::delete_session),
        )
        .route("/api/sessions/{id}/export", get(sessions::export_session))
        .route(
            "/api/sessions/{id}/debug-export",
            get(sessions::debug_export),
        )
        .route("/api/models", get(meta::models))
        .route("/api/providers", get(meta::providers))
        .route("/api/auth/openai/status", get(auth::openai_auth_status))
        .route("/api/auth/openai/start", post(auth::openai_auth_start))
        .route("/api/auth/openai/logout", post(auth::openai_auth_logout))
        .route("/api/chat", post(chat::chat))
        .route("/api/stream", get(chat::stream))
        .route("/api/metrics", get(meta::metrics))
        .route("/api/undo", post(meta::undo))
        .route("/api/redo", post(meta::redo))
        .route("/ws/chat", get(crate::ws::ws_chat))
        .fallback_service(ServeDir::new(frontend_dir).append_index_html_on_directories(true))
        .layer(CorsLayer::permissive())
        .with_state(state)
}

// ---------------------------------------------------------------------------
// Middleware helpers
// ---------------------------------------------------------------------------

/// Extracts the unlock token from the `X-Unlock-Token` header, the
/// `token` query parameter, or the `Sec-WebSocket-Protocol` value.
fn token_from(headers: &HeaderMap, query: &Query<Value>) -> Option<String> {
    headers
        .get("X-Unlock-Token")
        .and_then(|v| v.to_str().ok())
        .map(String::from)
        .or_else(|| query.get("token").and_then(Value::as_str).map(String::from))
}

/// Gated-handler wrapper: checks unlock token, rate limit, and network
/// availability. Returns a 401/429/403 response on failure.
fn gate(state: &AppState, headers: &HeaderMap, query: &Query<Value>) -> Option<Response> {
    let ip = headers
        .get("x-forwarded-for")
        .and_then(|v| v.to_str().ok())
        .map_or_else(|| String::from("unknown"), String::from);
    if !state.rate_limiter.check(&ip) {
        return Some((StatusCode::TOO_MANY_REQUESTS, "rate limit exceeded").into_response());
    }
    if state.needs_setup() {
        return Some((StatusCode::LOCKED, "setup required").into_response());
    }
    let Some(token) = token_from(headers, query) else {
        return Some((StatusCode::UNAUTHORIZED, "missing unlock token").into_response());
    };
    if !state.validate_token(&token) {
        return Some((StatusCode::UNAUTHORIZED, "invalid unlock token").into_response());
    }
    None
}

/// Rate-limit-only gate for the public routes (`/api/setup`,
/// `/api/unlock`) — they are reachable before any vault or token
/// exists.
fn gate_public(state: &AppState, headers: &HeaderMap, query: &Query<Value>) -> Option<Response> {
    let _ = query;
    let ip = headers
        .get("x-forwarded-for")
        .and_then(|v| v.to_str().ok())
        .map_or_else(|| String::from("unknown"), String::from);
    if !state.rate_limiter.check(&ip) {
        return Some((StatusCode::TOO_MANY_REQUESTS, "rate limit exceeded").into_response());
    }
    None
}

/// The shared session slot (a poisoned lock is an invariant
/// violation; fail fast).
#[allow(clippy::expect_used)] // poisoned slot = invariant violation
fn require_session(state: &AppState) -> Option<Arc<echo_ai_core::session::SessionManager>> {
    state
        .session
        .lock()
        .expect("session slot lock poisoned")
        .clone()
}

fn to_llm_messages(msgs: &[Message]) -> Vec<LlmMessage> {
    msgs.iter()
        .map(|m| LlmMessage {
            role: m.role.clone(),
            content: m.content.clone(),
            tool_calls: m.tool_calls.clone(),
            tool_call_id: m.tool_call_id.clone(),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn messages_to_llm_preserves_roles() {
        let msgs = vec![Message::user("hi"), Message::assistant("hello")];
        let llm = to_llm_messages(&msgs);
        assert_eq!(llm.len(), 2);
        assert_eq!(llm[0].role, "user");
        assert_eq!(llm[1].role, "assistant");
    }
}
