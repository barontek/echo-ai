//! Session routes: CRUD, rename, import, export, and debug-export.
//!
//! Depends on: `axum`, `serde`, `serde_json`, `echo-ai-core`, crate `state`, sibling gates.

use std::sync::Arc;

use axum::Json;
use axum::extract::{Path, Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use serde::Deserialize;
use serde_json::{Value, json};

use echo_ai_core::agent::message::Message;

use super::{gate, require_session};
use crate::state::AppState;

#[derive(Deserialize)]
pub(super) struct UpdateSessionBody {
    pub(super) title: Option<String>,
    pub(super) messages: Option<Vec<Message>>,
}

/// `GET /api/sessions`.
pub(super) async fn list_sessions(
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
pub(super) async fn create_session(
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
pub(super) async fn get_session(
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
        Ok(None) => (StatusCode::NOT_FOUND, "not found").into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
    }
}

/// `DELETE /api/sessions/{id}`.
pub(super) async fn delete_session(
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
pub(super) async fn update_session(
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
pub(super) async fn rename_session(
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
pub(super) async fn import_session(
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
pub(super) async fn export_session(
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
pub(super) async fn debug_export(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
    headers: HeaderMap,
    query: Query<Value>,
) -> Response {
    export_session(State(state), Path(id), headers, query).await
}
