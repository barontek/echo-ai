//! Auth routes: vault setup, unlock, logout, change-password, and OAuth token store.
//!
//! Depends on: `axum`, `serde`, `serde_json`, `echo-ai-core`, crate `state`, sibling gates.

use std::sync::Arc;

use axum::Json;
use axum::extract::{Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use serde::Deserialize;
use serde_json::{Value, json};

use super::{gate, gate_public, require_session};
use crate::state::AppState;

#[derive(Deserialize)]
pub(super) struct PasswordBody {
    pub(super) password: String,
}

#[derive(Deserialize)]
pub(super) struct ChangePasswordBody {
    pub(super) current_password: String,
    pub(super) new_password: String,
    pub(super) confirm: String,
}

#[derive(Deserialize)]
pub(super) struct OpenAiTokenBody {
    pub(super) token: String,
}

/// `POST /api/setup`: first-run vault creation.
pub(super) async fn setup(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    query: Query<Value>,
    Json(body): Json<PasswordBody>,
) -> Response {
    if let Some(resp) = gate_public(&state, &headers, &query) {
        return resp;
    }
    if !state.needs_setup() {
        return (StatusCode::CONFLICT, "already initialized").into_response();
    }
    if body.password.len() < 8 {
        return (
            StatusCode::BAD_REQUEST,
            "password must be at least 8 characters",
        )
            .into_response();
    }
    // Create the vault with the submitted password and fill the shared
    // session slot (the agent's tools and every handler see it via the
    // same `Arc`).
    let sm = match echo_ai_core::session::SessionManager::open(&state.data_dir, &body.password) {
        Ok(sm) => sm,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                format!("vault creation failed: {e}"),
            )
                .into_response();
        }
    };
    {
        #[allow(clippy::expect_used)] // poisoned slot = invariant violation
        let mut slot = state.session.lock().expect("session slot lock poisoned");
        *slot = Some(Arc::new(sm));
    }
    // Setup unlocks directly and returns the token, so the frontend
    // can skip the unlock screen.
    let token = state.unlock();
    Json(json!({ "status": "ok", "token": token, "message": "echo-ai configured and unlocked" }))
        .into_response()
}

/// `POST /api/unlock`: verify password, issue token.
pub(super) async fn unlock(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    query: Query<Value>,
    Json(body): Json<PasswordBody>,
) -> Response {
    if let Some(resp) = gate_public(&state, &headers, &query) {
        return resp;
    }
    if state.needs_setup() {
        return (StatusCode::LOCKED, "setup required").into_response();
    }
    // Verify by opening the vault directly — the session slot may be
    // empty (server started locked against the original implementation's vault), in
    // which case a successful open fills it.
    let sm = match echo_ai_core::session::SessionManager::open(&state.data_dir, &body.password) {
        Ok(sm) => Arc::new(sm),
        Err(_) => {
            return (StatusCode::UNAUTHORIZED, "wrong password").into_response();
        }
    };
    {
        #[allow(clippy::expect_used)] // poisoned slot = invariant violation
        let mut slot = state.session.lock().expect("session slot lock poisoned");
        if slot.is_none() {
            *slot = Some(sm);
        }
    }
    let token = state.unlock();
    Json(json!({ "status": "ok", "token": token })).into_response()
}

/// `POST /api/logout`.
pub(super) async fn logout(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    query: Query<Value>,
) -> Response {
    if let Some(resp) = gate(&state, &headers, &query) {
        return resp;
    }
    state.logout();
    StatusCode::OK.into_response()
}

/// `POST /api/change-password`.
pub(super) async fn change_password(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    query: Query<Value>,
    Json(body): Json<ChangePasswordBody>,
) -> Response {
    if let Some(resp) = gate(&state, &headers, &query) {
        return resp;
    }
    if body.new_password != body.confirm {
        return (StatusCode::BAD_REQUEST, "new passwords do not match").into_response();
    }
    // The current password must open the vault (the session slot may
    // hold an older open handle; the open is the authoritative check).
    if echo_ai_core::session::SessionManager::open(&state.data_dir, &body.current_password).is_err()
    {
        return (StatusCode::UNAUTHORIZED, "wrong current password").into_response();
    }
    let Some(sm) = require_session(&state) else {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            "session persistence disabled",
        )
            .into_response();
    };
    match sm.change_password(&body.new_password) {
        Ok(()) => StatusCode::OK.into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
    }
}

/// `GET /api/auth/openai/status`.
pub(super) async fn openai_auth_status(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    query: Query<Value>,
) -> Response {
    if let Some(resp) = gate(&state, &headers, &query) {
        return resp;
    }
    let Some(sm) = require_session(&state) else {
        return (StatusCode::SERVICE_UNAVAILABLE, "disabled").into_response();
    };
    let configured = sm.oauth_get("openai").ok().flatten().is_some();
    Json(json!({
        "state": if configured { "signed_in" } else { "signed_out" },
    }))
    .into_response()
}

/// `POST /api/auth/openai/start`.
pub(super) async fn openai_auth_start(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    query: Query<Value>,
    Json(body): Json<OpenAiTokenBody>,
) -> Response {
    if let Some(resp) = gate(&state, &headers, &query) {
        return resp;
    }
    let Some(sm) = require_session(&state) else {
        return (StatusCode::SERVICE_UNAVAILABLE, "disabled").into_response();
    };
    match sm.oauth_set("openai", &body.token) {
        Ok(()) => StatusCode::OK.into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
    }
}

/// `POST /api/auth/openai/logout`.
pub(super) async fn openai_auth_logout(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    query: Query<Value>,
) -> Response {
    if let Some(resp) = gate(&state, &headers, &query) {
        return resp;
    }
    let Some(sm) = require_session(&state) else {
        return (StatusCode::SERVICE_UNAVAILABLE, "disabled").into_response();
    };
    let _ = sm.oauth_delete("openai");
    StatusCode::OK.into_response()
}
