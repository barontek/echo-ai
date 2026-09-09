//! Status, health, config, models, metrics, and undo/redo routes.
//!
//! Depends on: `axum`, `serde_json`, crate `state`, sibling `gate`.

use std::sync::Arc;

use axum::Json;
use axum::extract::{Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use serde_json::{Value, json};

use super::gate;
use crate::state::AppState;

/// `GET /api/status`: vault gate for the frontend.
pub(super) async fn status(State(state): State<Arc<AppState>>) -> Json<Value> {
    let needs_setup = state.needs_setup();
    let locked = !needs_setup && {
        // A poisoned auth lock is an invariant violation; fail fast.
        #[allow(clippy::expect_used)] // poisoned lock = invariant violation
        let auth = state.auth.lock().expect("auth lock poisoned");
        auth.state == crate::state::ServerState::Locked
    };
    Json(json!({ "locked": locked, "needs_setup": needs_setup }))
}

/// `GET /api/health`.
pub(super) async fn health() -> Json<Value> {
    Json(json!({ "status": "ok" }))
}

/// `GET /api/health/detailed` (unlocked).
pub(super) async fn health_detailed(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    query: Query<Value>,
) -> Response {
    if let Some(resp) = gate(&state, &headers, &query) {
        return resp;
    }
    let sessions = {
        #[allow(clippy::expect_used)] // poisoned slot = invariant violation
        state
            .session
            .lock()
            .expect("session slot lock poisoned")
            .as_ref()
            .map_or(0, |sm| sm.list_sessions().map_or(0, |l| l.len()))
    };
    Json(json!({
        "status": "ok",
        "sessions": sessions,
        "tools": state.registry.len(),
    }))
    .into_response()
}

/// `GET /api/config`: public config (provider names, model, limits).
pub(super) async fn public_config(State(state): State<Arc<AppState>>) -> Json<Value> {
    #[allow(clippy::expect_used)] // poisoned slot = invariant violation
    let session_enabled = state.session.lock().expect("session slot lock").is_some();
    Json(json!({
        "config": {
            "provider": state.config.agent.provider,
            "model": state.config.agent.model,
            "temperature": state.config.agent.temperature,
            "max_iterations": state.config.agent.max_iterations,
            "session_enabled": session_enabled,
        }
    }))
}

/// Query parameters for `GET /api/models`.
#[derive(serde::Deserialize, Default)]
pub(super) struct ModelsQuery {
    /// Optional provider catalog name to list models for (e.g. `ollama`, `opencode_zen`).
    pub(super) provider: Option<String>,
}

/// `GET /api/models`: live model list for the configured or requested provider.
pub(super) async fn models(
    State(state): State<Arc<AppState>>,
    Query(query): Query<ModelsQuery>,
) -> Json<Value> {
    let provider = query
        .provider
        .unwrap_or_else(|| state.config.agent.provider.clone());
    let base_url = echo_ai_core::llm::factory::models_base_url(&state.config, &provider);
    let token = state
        .config
        .providers
        .get(&provider)
        .cloned()
        .or_else(|| state.config.providers.get("opencode").cloned());
    let list = echo_ai_core::llm::factory::list_models(
        &provider,
        &base_url,
        token.as_deref(),
        state.http.as_ref(),
    )
    .await
    .unwrap_or_default();
    Json(json!({ "models": list }))
}

/// `GET /api/providers`.
pub(super) async fn providers() -> Json<Value> {
    Json(json!({
        "providers": echo_ai_core::llm::factory::PROVIDERS,
        "effort_supported": [],
        "effort_options": {},
    }))
}

/// `GET /api/metrics`: Prometheus text.
pub(super) async fn metrics(State(state): State<Arc<AppState>>) -> Response {
    (StatusCode::OK, state.metrics.render()).into_response()
}

/// `POST /api/undo`.
pub(super) async fn undo(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    query: Query<Value>,
) -> Response {
    if let Some(resp) = gate(&state, &headers, &query) {
        return resp;
    }
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    let mut tracker = state.tracker.lock().expect("tracker lock poisoned");
    match tracker.undo() {
        Ok(snapshot) => Json(json!({
            "path": snapshot.path.to_string_lossy(),
            "ok": true,
        }))
        .into_response(),
        Err(e) => (StatusCode::CONFLICT, e.to_string()).into_response(),
    }
}

/// `POST /api/redo`.
pub(super) async fn redo(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    query: Query<Value>,
) -> Response {
    if let Some(resp) = gate(&state, &headers, &query) {
        return resp;
    }
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    let mut tracker = state.tracker.lock().expect("tracker lock poisoned");
    match tracker.redo() {
        Ok(snapshot) => Json(json!({
            "path": snapshot.path.to_string_lossy(),
            "ok": true,
        }))
        .into_response(),
        Err(e) => (StatusCode::CONFLICT, e.to_string()).into_response(),
    }
}
