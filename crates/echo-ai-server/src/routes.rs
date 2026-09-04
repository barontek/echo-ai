//! REST routes: status/health, auth (setup/unlock/logout), sessions,
//! chat (blocking + `SSE`), models, metrics, undo/redo, static files.
//!
//! Depends on: `axum`, `tower-http`, `echo-ai-core`, crate `state`.

use std::sync::Arc;

use axum::body::Body;
use axum::extract::{Path, Query, State};
use axum::http::{HeaderMap, StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::Deserialize;
use serde_json::{Value, json};
use tower_http::cors::CorsLayer;
use tower_http::services::ServeDir;

use echo_ai_core::agent::message::Message;
use echo_ai_core::agent::run::{AgentEvent, AgentResult};
use echo_ai_core::llm::provider::LlmMessage;

use tokio_util::sync::CancellationToken;

use crate::state::AppState;

/// Builds the router (REST + `SSE` + static + `WS`).
pub fn router(state: Arc<AppState>, frontend_dir: std::path::PathBuf) -> Router {
    Router::new()
        .route("/api/status", get(status))
        .route("/api/health", get(health))
        .route("/api/health/detailed", get(health_detailed))
        .route("/api/config", get(public_config))
        .route("/api/setup", post(setup))
        .route("/api/unlock", post(unlock))
        .route("/api/logout", post(logout))
        .route("/api/change-password", post(change_password))
        .route("/api/sessions", get(list_sessions).post(create_session))
        .route("/api/sessions/rename", post(rename_session))
        .route("/api/sessions/import", post(import_session))
        .route(
            "/api/sessions/{id}",
            get(get_session).put(update_session).delete(delete_session),
        )
        .route("/api/sessions/{id}/export", get(export_session))
        .route("/api/sessions/{id}/debug-export", get(debug_export))
        .route("/api/models", get(models))
        .route("/api/providers", get(providers))
        .route("/api/auth/openai/status", get(openai_auth_status))
        .route("/api/auth/openai/start", post(openai_auth_start))
        .route("/api/auth/openai/logout", post(openai_auth_logout))
        .route("/api/chat", post(chat))
        .route("/api/stream", get(stream))
        .route("/api/metrics", get(metrics))
        .route("/api/undo", post(undo))
        .route("/api/redo", post(redo))
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

// ---------------------------------------------------------------------------
// Status / health
// ---------------------------------------------------------------------------

/// `GET /api/status`: vault gate for the frontend.
async fn status(State(state): State<Arc<AppState>>) -> Json<Value> {
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
async fn health() -> Json<Value> {
    Json(json!({ "status": "ok" }))
}

/// `GET /api/health/detailed` (unlocked).
async fn health_detailed(
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
async fn public_config(State(state): State<Arc<AppState>>) -> Json<Value> {
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

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
struct PasswordBody {
    password: String,
}

#[derive(Deserialize)]
struct ChangePasswordBody {
    current_password: String,
    new_password: String,
    confirm: String,
}

/// `POST /api/setup`: first-run vault creation.
async fn setup(
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
async fn unlock(
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
async fn logout(
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
async fn change_password(
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

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

/// `GET /api/sessions`.
async fn list_sessions(
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
    match sm.list_sessions() {
        Ok(list) => Json(json!({
            "sessions": list.iter().map(|s| json!({
                "id": s.id,
                "title": s.title,
                "title_generation_attempted": s.title_generation_attempted,
                "created_at": s.created_at,
            })).collect::<Vec<_>>(),
        }))
        .into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
    }
}

/// `POST /api/sessions`.
async fn create_session(
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
    let session = sm.create_session();
    let id = session.id.clone();
    match sm.save_session(&session) {
        Ok(()) => (StatusCode::CREATED, Json(json!({ "session_id": id }))).into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
    }
}

/// `GET /api/sessions/{id}`.
async fn get_session(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
    headers: HeaderMap,
    query: Query<Value>,
) -> Response {
    if let Some(resp) = gate(&state, &headers, &query) {
        return resp;
    }
    let Some(sm) = require_session(&state) else {
        return (StatusCode::SERVICE_UNAVAILABLE, "disabled").into_response();
    };
    match sm.load_session(&id) {
        Ok(Some(s)) => Json(json!({
            "session_id": s.id,
            "title": s.title,
            "messages": s.messages,
            // Branching metadata is not tracked yet; the frontend
            // treats the absent field as "no branches".
        }))
        .into_response(),
        Ok(None) => (StatusCode::NOT_FOUND, "not found").into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
    }
}

/// `DELETE /api/sessions/{id}`.
async fn delete_session(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
    headers: HeaderMap,
    query: Query<Value>,
) -> Response {
    if let Some(resp) = gate(&state, &headers, &query) {
        return resp;
    }
    let Some(sm) = require_session(&state) else {
        return (StatusCode::SERVICE_UNAVAILABLE, "disabled").into_response();
    };
    match sm.delete_session(&id) {
        Ok(true) => StatusCode::OK.into_response(),
        Ok(false) => (StatusCode::NOT_FOUND, "not found").into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
    }
}

/// `PUT /api/sessions/{id}` (update title + messages).
#[derive(Deserialize)]
struct UpdateSessionBody {
    title: Option<String>,
    messages: Option<Vec<Message>>,
}

async fn update_session(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
    headers: HeaderMap,
    query: Query<Value>,
    Json(body): Json<UpdateSessionBody>,
) -> Response {
    if let Some(resp) = gate(&state, &headers, &query) {
        return resp;
    }
    let Some(sm) = require_session(&state) else {
        return (StatusCode::SERVICE_UNAVAILABLE, "disabled").into_response();
    };
    let mut session = match sm.load_session(&id) {
        Ok(Some(s)) => s,
        Ok(None) => return (StatusCode::NOT_FOUND, "not found").into_response(),
        Err(e) => return (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
    };
    if let Some(title) = body.title {
        session.title = Some(title);
    }
    if let Some(messages) = body.messages {
        session.messages = messages;
    }
    match sm.save_session(&session) {
        Ok(()) => Json(json!({
            "session_id": session.id,
            "title": session.title,
            "messages": session.messages,
        }))
        .into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
    }
}

/// `POST /api/sessions/rename`.
async fn rename_session(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    query: Query<Value>,
    Json(body): Json<Value>,
) -> Response {
    if let Some(resp) = gate(&state, &headers, &query) {
        return resp;
    }
    let Some(sm) = require_session(&state) else {
        return (StatusCode::SERVICE_UNAVAILABLE, "disabled").into_response();
    };
    let id = body
        .get("session_id")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let title = body
        .get("new_title")
        .and_then(Value::as_str)
        .unwrap_or_default();
    match sm.rename_session(id, title) {
        Ok(true) => StatusCode::OK.into_response(),
        Ok(false) => (StatusCode::NOT_FOUND, "not found").into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
    }
}

/// `POST /api/sessions/import`.
async fn import_session(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    query: Query<Value>,
    Json(body): Json<Value>,
) -> Response {
    if let Some(resp) = gate(&state, &headers, &query) {
        return resp;
    }
    let Some(sm) = require_session(&state) else {
        return (StatusCode::SERVICE_UNAVAILABLE, "disabled").into_response();
    };
    let id = body.get("id").and_then(Value::as_str).unwrap_or_default();
    let session = sm.load_session(id).ok().flatten();
    let mut session = session.unwrap_or_else(|| sm.create_session());
    if let Some(messages) = body.get("messages").and_then(Value::as_array) {
        session.messages =
            serde_json::from_value(Value::Array(messages.clone())).unwrap_or_default();
    }
    let id = session.id.clone();
    match sm.save_session(&session) {
        Ok(()) => Json(json!({ "session_id": id })).into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
    }
}

/// `GET /api/sessions/{id}/export` — plaintext export (unlocked only).
async fn export_session(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
    headers: HeaderMap,
    query: Query<Value>,
) -> Response {
    if let Some(resp) = gate(&state, &headers, &query) {
        return resp;
    }
    let Some(sm) = require_session(&state) else {
        return (StatusCode::SERVICE_UNAVAILABLE, "disabled").into_response();
    };
    match sm.load_session(&id) {
        Ok(Some(s)) => Json(json!({
            "session_id": s.id,
            "title": s.title,
            "messages": s.messages,
        }))
        .into_response(),
        _ => (StatusCode::NOT_FOUND, "not found").into_response(),
    }
}

/// `GET /api/sessions/{id}/debug-export`.
async fn debug_export(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
    headers: HeaderMap,
    query: Query<Value>,
) -> Response {
    export_session(State(state), Path(id), headers, query).await
}

// ---------------------------------------------------------------------------
// Models / providers
// ---------------------------------------------------------------------------

/// `GET /api/models`: live model list for the configured provider.
async fn models(State(state): State<Arc<AppState>>) -> Json<Value> {
    let provider = state.config.agent.provider.clone();
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
async fn providers() -> Json<Value> {
    Json(json!({
        "providers": echo_ai_core::llm::factory::PROVIDERS,
        "effort_supported": [],
        "effort_options": {},
    }))
}

// ---------------------------------------------------------------------------
// OpenAI auth (token storage only; device flow is a client-side concern)
// ---------------------------------------------------------------------------

async fn openai_auth_status(
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

#[derive(Deserialize)]
struct OpenAiTokenBody {
    token: String,
}

async fn openai_auth_start(
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

async fn openai_auth_logout(
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

// ---------------------------------------------------------------------------
// Chat (blocking + SSE)
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
struct ChatBody {
    session_id: Option<String>,
    messages: Option<Vec<Message>>,
    content: Option<String>,
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

/// `POST /api/chat`: blocking turn. Returns the final content.
async fn chat(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    query: Query<Value>,
    Json(body): Json<ChatBody>,
) -> Response {
    if let Some(resp) = gate(&state, &headers, &query) {
        return resp;
    }
    let mut messages = match body.messages {
        Some(m) => to_llm_messages(&m),
        None => Vec::new(),
    };
    if let Some(content) = body.content {
        messages.push(LlmMessage {
            role: String::from("user"),
            content,
            tool_calls: Vec::new(),
            tool_call_id: None,
        });
    }

    let _guard = state.turn_lock.lock().await;
    let (tx, mut rx) = tokio::sync::mpsc::channel(64);
    let cancel = CancellationToken::new();
    let agent = Arc::clone(&state.agent);
    let session_id = body.session_id.clone();
    let handle = tokio::spawn(async move {
        let result = agent.run(messages, tx, cancel, session_id.clone()).await;
        (result, session_id)
    });

    // Drain events (nothing to forward for a blocking call), keep the
    // task alive until done.
    while rx.recv().await.is_some() {}
    let Ok((result, session_id)) = handle.await else {
        return (StatusCode::INTERNAL_SERVER_ERROR, "run task failed").into_response();
    };
    match result {
        Ok(res) => {
            maybe_persist(&state, session_id.as_deref(), &res);
            Json(json!({
                "content": res.content,
                "thinking": res.thinking,
            }))
            .into_response()
        }
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
    }
}

/// Persists a run's transcript into the session store (if enabled).
fn maybe_persist(state: &AppState, session_id: Option<&str>, result: &AgentResult) {
    let Some(sm) = require_session(state) else {
        return;
    };
    let Some(id) = session_id else {
        return;
    };
    let session = sm.load_session(id).ok().flatten();
    let Some(mut session) = session else {
        return;
    };
    session.messages = result
        .messages
        .iter()
        .map(|m| Message {
            id: None,
            parent_id: None,
            fork_group_id: None,
            role: m.role.clone(),
            content: m.content.clone(),
            thinking: None,
            phase: None,
            provider_state: None,
            tool_calls: m.tool_calls.clone(),
            tool_call_id: m.tool_call_id.clone(),
            tool_name: None,
            error_category: None,
            timestamp: echo_ai_core::agent::message::now_epoch_secs(),
        })
        .collect();
    let _ = sm.save_session(&session);
}

/// `GET /api/stream`: `SSE` streaming of one turn.
async fn stream(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    query: Query<Value>,
) -> Response {
    if let Some(resp) = gate(&state, &headers, &query) {
        return resp;
    }
    let content = query
        .get("content")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let session_id = query
        .get("session_id")
        .and_then(Value::as_str)
        .map(String::from);

    let _guard = state.turn_lock.lock().await;
    let messages = vec![LlmMessage {
        role: String::from("user"),
        content: String::from(content),
        tool_calls: Vec::new(),
        tool_call_id: None,
    }];
    let (tx, mut rx) = tokio::sync::mpsc::channel(64);
    let cancel = CancellationToken::new();
    let agent = Arc::clone(&state.agent);
    let handle = tokio::spawn(async move {
        let result = agent.run(messages, tx, cancel, session_id.clone()).await;
        (result, session_id)
    });

    // The stream owns its own handle to the state.
    let stream_state = state.clone();
    let stream = async_stream::stream! {
        let state_ref = stream_state.as_ref();
        while let Some(event) = rx.recv().await {
            let frame = match event {
                AgentEvent::Chunk { content, thinking } => {
                    serde_json::json!({ "type": "content", "delta": content, "thinking": thinking })
                }
                AgentEvent::ToolStart { name, args } => {
                    serde_json::json!({ "type": "tool_start", "name": name, "args": args })
                }
                AgentEvent::ToolEnd { name, ok, summary } => {
                    serde_json::json!({ "type": "tool_end", "name": name, "ok": ok, "summary": summary })
                }
                AgentEvent::Error { message } => {
                    serde_json::json!({ "type": "error", "message": message })
                }
                AgentEvent::Done => break,
            };
            yield Ok::<_, std::convert::Infallible>(format!("data: {frame}\n\n"));
        }
        if let Ok((result, session_id)) = handle.await {
            if let Ok(res) = &result {
                maybe_persist(state_ref, session_id.as_deref(), res);
                let done = serde_json::json!({
                    "type": "done",
                    "content": res.content,
                    "thinking": res.thinking,
                    "hit_iteration_cap": res.hit_iteration_cap,
                });
                yield Ok::<_, std::convert::Infallible>(format!("data: {done}\n\n"));
            } else if let Err(e) = &result {
                let err = serde_json::json!({ "type": "error", "message": e.to_string() });
                yield Ok::<_, std::convert::Infallible>(format!("data: {err}\n\n"));
            }
        }
    };

    (
        StatusCode::OK,
        [
            (header::CONTENT_TYPE, "text/event-stream"),
            (header::CACHE_CONTROL, "no-cache"),
        ],
        Body::from_stream(stream),
    )
        .into_response()
}

// ---------------------------------------------------------------------------
// Metrics / undo / redo
// ---------------------------------------------------------------------------

/// `GET /api/metrics`: Prometheus text.
async fn metrics(State(state): State<Arc<AppState>>) -> Response {
    (StatusCode::OK, state.metrics.render()).into_response()
}

/// `POST /api/undo`.
async fn undo(
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
async fn redo(
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
