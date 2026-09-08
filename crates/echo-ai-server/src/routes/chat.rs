//! Chat routes: blocking `/api/chat` and SSE streaming `/api/stream`.
//!
//! Depends on: `axum`, `async_stream`, `echo-ai-core`, `tokio_util`, crate `state`.

use std::sync::Arc;

use axum::Json;
use axum::body::Body;
use axum::extract::{Query, State};
use axum::http::{HeaderMap, StatusCode, header};
use axum::response::{IntoResponse, Response};
use serde::Deserialize;
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;

use echo_ai_core::agent::message::Message;
use echo_ai_core::agent::run::{AgentEvent, AgentResult};
use echo_ai_core::llm::provider::LlmMessage;

use super::{gate, require_session, to_llm_messages};
use crate::state::AppState;

#[derive(Deserialize)]
pub(super) struct ChatBody {
    pub(super) session_id: Option<String>,
    pub(super) messages: Option<Vec<Message>>,
    pub(super) content: Option<String>,
}

/// `POST /api/chat`: blocking turn. Returns the final content.
pub(super) async fn chat(
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
pub(super) fn maybe_persist(state: &AppState, session_id: Option<&str>, result: &AgentResult) {
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
pub(super) async fn stream(
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
