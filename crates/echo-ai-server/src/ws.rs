//! `/ws/chat`: the real-time chat protocol (frames mirroring the C
//! version's `routes_ws_*` handlers).
//!
//! Client → server: `message`, `stop`, `approval_response`,
//! `ask_user_response`, `edit`, `regenerate`, `branch_switch`,
//! `branch_info`, and a bare provider-config frame.
//!
//! Server → client: `session_start`, `ready`, `history`, `content`,
//! `tool_start`, `tool_end`, `approval_request`, `done`, `title_updated`,
//! `error`, `branch_info`.
//!
//! The agent's `AskUser` callback is bridged over the socket: an
//! `approval_request` frame carries a `request_id`; the matching
//! `approval_response`/`ask_user_response` resolves the pending await.
//!
//! Depends on: `axum` (`ws`), `futures-util`, `tokio`, `echo-ai-core`,
//! crate `state`.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use axum::extract::ws::{Message as WsMessage, WebSocket, WebSocketUpgrade};
use axum::extract::{Query, State};
use axum::http::HeaderMap;
use axum::response::Response;
use futures_util::{SinkExt, StreamExt};
use serde_json::{Value, json};

use echo_ai_core::agent::message::Message;
use echo_ai_core::agent::run::{Agent, AgentEvent};
use echo_ai_core::llm::provider::LlmMessage;
use echo_ai_core::tools::tool::{AskUser, ToolError};
use tokio::sync::{mpsc, oneshot};
use tokio_util::sync::CancellationToken;

use crate::state::AppState;

/// Random hex id for pending requests.
fn request_id() -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut bytes = [0u8; 8];
    rand::RngCore::fill_bytes(&mut rand::thread_rng(), &mut bytes);
    let mut out = String::with_capacity(16);
    for b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
    }
    out
}

/// Bridged `AskUser`: sends a question frame and awaits the response.
struct SocketAskUser {
    tx: mpsc::Sender<Value>,
    pending: Arc<Mutex<HashMap<String, oneshot::Sender<Option<String>>>>>,
}

impl AskUser for SocketAskUser {
    fn ask(
        &self,
        prompt: &str,
    ) -> futures_util::future::BoxFuture<'_, echo_ai_core::Result<Option<String>>> {
        // Clone the channel handles so the future does not borrow self
        // (keeps the trait dyn-compatible).
        let tx = self.tx.clone();
        let pending = Arc::clone(&self.pending);
        let prompt = String::from(prompt);
        Box::pin(async move {
            let id = request_id();
            let (otx, orx) = oneshot::channel();
            // A poisoned pending-map is an invariant violation; fail
            // fast rather than strand the awaiting caller silently.
            #[allow(clippy::expect_used)] // poisoned lock = invariant violation
            pending
                .lock()
                .expect("pending lock")
                .insert(id.clone(), otx);
            let _ = tx
                .send(json!({
                    "type": "ask_user",
                    "request_id": id,
                    "question": prompt,
                }))
                .await;
            match orx.await {
                Ok(answer) => Ok(answer),
                Err(_) => Ok(None),
            }
        })
    }

    fn ask_approval(
        &self,
        tool: &str,
        args: &str,
    ) -> futures_util::future::BoxFuture<'_, echo_ai_core::Result<Option<String>>> {
        let tx = self.tx.clone();
        let pending = Arc::clone(&self.pending);
        let tool = String::from(tool);
        let args = String::from(args);
        Box::pin(async move {
            let id = request_id();
            let (otx, orx) = oneshot::channel();
            #[allow(clippy::expect_used)] // poisoned lock = invariant violation
            pending
                .lock()
                .expect("pending lock")
                .insert(id.clone(), otx);
            let _ = tx
                .send(json!({
                    "type": "approval_request",
                    "request_id": id,
                    "tool_name": tool,
                    "arguments": args,
                }))
                .await;
            match orx.await {
                Ok(answer) => Ok(answer),
                Err(_) => Ok(None),
            }
        })
    }
}

/// Per-connection chat state.
struct WsChat {
    state: Arc<AppState>,
    tx: mpsc::Sender<Value>,
    session_id: String,
    history: Vec<Message>,
    ask_user: Arc<SocketAskUser>,
    running: bool,
    cancel: Option<CancellationToken>,
}

/// `GET /ws/chat` handler.
///
/// # Panics
/// Cannot panic in practice: the 401 response build with a static body
/// is infallible.
#[allow(clippy::expect_used)] // invariant: static body build cannot fail
pub async fn ws_chat(
    State(state): State<Arc<AppState>>,
    ws: WebSocketUpgrade,
    headers: HeaderMap,
    Query(query): Query<Value>,
) -> Response {
    // Token comes from the `Sec-WebSocket-Protocol` subprotocol value
    // (browsers can't set headers), or the `X-Unlock-Token` header.
    let token = headers
        .get("X-Unlock-Token")
        .and_then(|v| v.to_str().ok())
        .map(String::from)
        .or_else(|| {
            headers
                .get("sec-websocket-protocol")
                .and_then(|v| v.to_str().ok())
                .and_then(|v| v.split(',').next())
                .map(|v| v.trim().to_string())
        });
    let Some(token) = token.filter(|t| state.validate_token(t)) else {
        return Response::builder()
            .status(401)
            .body(axum::body::Body::from("invalid unlock token"))
            .expect("response build");
    };
    let _ = token;
    let session_id = query
        .get("session_id")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();

    ws.on_upgrade(move |socket| handle_socket(state, socket, session_id))
}

/// Runs the per-connection socket loop.
async fn handle_socket(state: Arc<AppState>, socket: WebSocket, session_id: String) {
    let (mut sink, mut stream) = socket.split();
    let (tx, mut rx) = mpsc::channel::<Value>(128);
    let pending = Arc::new(Mutex::new(HashMap::new()));
    let ask_user = Arc::new(SocketAskUser {
        tx: tx.clone(),
        pending: pending.clone(),
    });

    let mut chat = WsChat {
        state: state.clone(),
        tx: tx.clone(),
        session_id: session_id.clone(),
        history: Vec::new(),
        ask_user: ask_user.clone(),
        running: false,
        cancel: None,
    };

    // Writer task: drains the frame channel into the socket.
    let writer = tokio::spawn(async move {
        while let Some(frame) = rx.recv().await {
            let text = frame.to_string();
            if sink.send(WsMessage::Text(text.into())).await.is_err() {
                break;
            }
        }
        let _ = sink.close().await;
    });

    // Load history for the session (if any).
    let session_opt = {
        #[allow(clippy::expect_used)] // poisoned slot = invariant violation
        chat.state
            .session
            .lock()
            .expect("session slot lock poisoned")
            .clone()
    };
    if let Some(sm) = session_opt.as_ref()
        && let Ok(Some(session)) = sm.load_session(&chat.session_id)
    {
        chat.history = session.messages;
    }
    let _ = tx
        .send(json!({
            "type": "session_start",
            "session_id": chat.session_id,
            "history": chat.history,
        }))
        .await;
    let _ = tx.send(json!({ "type": "ready" })).await;

    while let Some(Ok(msg)) = stream.next().await {
        match msg {
            WsMessage::Text(text) => {
                handle_frame(&mut chat, &text).await;
            }
            WsMessage::Close(_) => break,
            _ => {}
        }
    }

    // Teardown: cancel any running turn and close the writer.
    if let Some(cancel) = chat.cancel.take() {
        cancel.cancel();
    }
    drop(chat.tx);
    let _ = writer.await;
}

/// Dispatches one client frame.
///
/// The length is inherent: one match arm per protocol frame type (the C
/// version's `routes_ws_handlers.c` had the same shape). Splitting
/// would scatter the protocol across helpers without reducing
/// complexity.
#[allow(clippy::too_many_lines)] // protocol table: one arm per frame type
async fn handle_frame(chat: &mut WsChat, text: &str) {
    let Ok(frame) = serde_json::from_str::<Value>(text) else {
        let _ = chat
            .tx
            .send(json!({ "type": "error", "message": "malformed frame" }))
            .await;
        return;
    };

    let frame_type = frame.get("type").and_then(Value::as_str).unwrap_or("");
    match frame_type {
        "message" => {
            let content = frame
                .get("content")
                .and_then(Value::as_str)
                .unwrap_or_default();
            if content.is_empty() || chat.running {
                return;
            }
            let session_id = frame
                .get("session_id")
                .and_then(Value::as_str)
                .map_or_else(|| chat.session_id.clone(), String::from);
            chat.session_id = session_id.clone();
            chat.history.push(Message::user(content));
            start_turn(chat).await;
        }
        "stop" => {
            if let Some(cancel) = &chat.cancel {
                cancel.cancel();
            }
            // The persist task emits the terminal `done` once the run
            // unwinds (cancelled runs produce a plain done frame).
        }
        "approval_response" => {
            let id = frame
                .get("request_id")
                .and_then(Value::as_str)
                .unwrap_or_default();
            let approved = frame
                .get("approved")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            resolve_pending(&chat.ask_user, id, approved.then(|| String::from("yes")));
        }
        "ask_user_response" => {
            let id = frame
                .get("request_id")
                .and_then(Value::as_str)
                .unwrap_or_default();
            let answer = frame
                .get("answer")
                .and_then(Value::as_str)
                .map(String::from);
            resolve_pending(&chat.ask_user, id, answer);
        }
        "regenerate" => {
            if chat.running {
                return;
            }
            // Drop the last assistant message and re-run the last user
            // message.
            while let Some(last) = chat.history.last() {
                if last.role == "assistant" {
                    chat.history.pop();
                } else {
                    break;
                }
            }
            if !chat.history.is_empty() {
                start_turn(chat).await;
            }
        }
        "edit" => {
            if chat.running {
                return;
            }
            let index = frame
                .get("index")
                .and_then(Value::as_u64)
                .and_then(|v| usize::try_from(v).ok())
                .unwrap_or(0);
            let content = frame
                .get("content")
                .and_then(Value::as_str)
                .unwrap_or_default();
            if index < chat.history.len() {
                chat.history.truncate(index + 1);
                chat.history[index] = Message::user(content);
                start_turn(chat).await;
            }
        }
        "branch_switch" => {
            #[allow(clippy::expect_used)] // poisoned slot = invariant violation
            let session_opt = chat
                .state
                .session
                .lock()
                .expect("session slot lock poisoned")
                .clone();
            if let Some(sm) = session_opt.as_ref() {
                let id = frame
                    .get("session_id")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                if let Ok(Some(session)) = sm.load_session(id) {
                    chat.session_id = id.to_string();
                    chat.history = session.messages;
                    let _ = chat
                        .tx
                        .send(json!({ "type": "history", "messages": chat.history }))
                        .await;
                }
            }
        }
        "branch_info" => {
            let _ = chat
                .tx
                .send(json!({
                    "type": "branch_info",
                    "session_id": chat.session_id,
                    "branches": [],
                }))
                .await;
        }
        // Bare provider-config frame (no type): ignored for now (the
        // agent is built from config at startup).
        "" => {
            if frame.get("provider").is_some() {
                let _ = chat
                    .tx
                    .send(json!({ "type": "error", "message": "provider switch not supported" }))
                    .await;
            }
        }
        _ => {
            let _ = chat
                .tx
                .send(json!({ "type": "error", "message": format!("unknown frame type {frame_type}") }))
                .await;
        }
    }
}

/// Resolves a pending ask/approval with the given answer.
/// Resolves a pending ask/approval with the given answer.
///
/// # Panics
/// Same poisoned-lock policy as the rest of the server: fail fast.
#[allow(clippy::expect_used)] // poisoned lock = invariant violation
fn resolve_pending(ask_user: &SocketAskUser, id: &str, answer: Option<String>) {
    let mut pending = ask_user.pending.lock().expect("pending lock");
    if let Some(tx) = pending.remove(id) {
        let _ = tx.send(answer);
        return;
    }
    // The web frontend's `ask_user_response` carries no request_id;
    // with a single pending question the intent is unambiguous.
    if id.is_empty() && pending.len() == 1 {
        let (_, tx) = pending.drain().next().expect("len checked");
        let _ = tx.send(answer);
    }
}

/// Starts the agent run for the current history.
///
/// The length is inherent: spawn the run, forward events, join,
/// persist, and emit `done` — each step needs the previous one's
/// handles. the original implementation's `routes_ws_chat.c` had the same shape.
#[allow(clippy::too_many_lines)] // linear spawn/join orchestration
async fn start_turn(chat: &mut WsChat) {
    let messages: Vec<LlmMessage> = chat
        .history
        .iter()
        .map(|m| LlmMessage {
            role: m.role.clone(),
            content: m.content.clone(),
            tool_calls: m.tool_calls.clone(),
            tool_call_id: m.tool_call_id.clone(),
        })
        .collect();

    let cancel = CancellationToken::new();
    chat.cancel = Some(cancel.clone());
    chat.running = true;

    let agent = Arc::clone(&chat.state.agent);
    let (event_tx, mut event_rx) = mpsc::channel::<AgentEvent>(64);
    let out_tx = chat.tx.clone();
    let ask_user = Arc::clone(&chat.ask_user);
    let state = Arc::clone(&chat.state);
    let session_id = chat.session_id.clone();
    let history_len = chat.history.len();

    // Feed the ask_user bridge into the run via a mutable-holder.
    let agent_with_ask = Arc::new(Agent {
        provider: agent.provider.clone(),
        registry: agent.registry.clone(),
        config: agent.config.clone(),
        safety: agent.safety.clone(),
        app_config: agent.app_config.clone(),
        session: agent.session.clone(),
        tracker: agent.tracker.clone(),
        ask_user: Some(ask_user as Arc<dyn AskUser>),
        http: agent.http.clone(),
    });

    let run_out_tx = out_tx.clone();
    let forward_out_tx = out_tx.clone();
    let forward_sid = session_id.clone();
    let run_handle = tokio::spawn(async move {
        let _ = run_out_tx
            .send(json!({ "type": "turn_start", "history_len": history_len }))
            .await;
        let result = agent_with_ask.run(messages, event_tx, cancel, Some(session_id.clone()))
            .await;
        (result, session_id, state)
    });

    // Forward agent events as frames (C frontend protocol shapes:
    // `tool_name`/`arguments` on tool frames, `content` on content and
    // error frames, `session_id` everywhere it helps route).
    let forward_handle = tokio::spawn(async move {
        while let Some(event) = event_rx.recv().await {
            let frame = match event {
                AgentEvent::Chunk { content, .. } => {
                    json!({ "type": "content", "content": content, "session_id": forward_sid })
                }
                AgentEvent::ToolStart { name, args } => json!({
                    "type": "tool_start",
                    "tool_name": name,
                    "arguments": args,
                    "session_id": forward_sid,
                }),
                AgentEvent::ToolEnd { name, ok, summary } => json!({
                    "type": "tool_end",
                    "tool_name": name,
                    "ok": ok,
                    "summary": summary,
                    "session_id": forward_sid,
                }),
                AgentEvent::Error { message } => {
                    json!({ "type": "error", "content": message, "session_id": forward_sid })
                }
                AgentEvent::Done => continue,
            };
            if forward_out_tx.send(frame).await.is_err() {
                break;
            }
        }
    });

    // When the run finishes, persist, emit the C-protocol `done`, and
    // generate a first-turn title (`title_updated`).
    // # Panics: `expect` on the run task is invariant-fail-fast (the
    // task was just spawned and cannot be aborted here).
    #[allow(clippy::expect_used)] // spawned-task join cannot fail here
    let persist = tokio::spawn(async move {
        let (result, session_id, state) = run_handle.await.expect("run task");
        let mut done = json!({ "type": "done", "session_id": session_id });
        let mut final_messages: Option<Vec<Message>> = None;
        match result {
            Ok(res) => {
                done["content"] = json!(res.content);
                done["hit_iteration_cap"] = json!(res.hit_iteration_cap);
                let tool_calls: Vec<_> = res
                    .messages
                    .iter()
                    .rev()
                    .find(|m| m.role == "assistant")
                    .map(|m| m.tool_calls.clone())
                    .unwrap_or_default();
                done["has_tools"] = json!(!tool_calls.is_empty());
                done["tool_calls"] = json!(tool_calls);
                final_messages = Some(
                    res.messages
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
                        .collect(),
                );
            }
            Err(echo_ai_core::agent::run::AgentError::Cancelled) => {
                // Stopped by the user: the frontend finalizes on a plain
                // done frame.
            }
            Err(e) => {
                let _ = out_tx
                    .send(json!({
                        "type": "error",
                        "content": e.to_string(),
                        "session_id": session_id,
                    }))
                    .await;
                done["content"] = json!("");
            }
        }
        if let Some(messages) = final_messages
            && let Some(sm) = {
                #[allow(clippy::expect_used)] // poisoned slot = invariant violation
                state
                    .session
                    .lock()
                    .expect("session slot lock poisoned")
                    .clone()
            }
            && let Ok(Some(mut session)) = sm.load_session(&session_id)
        {
            session.messages = messages;
            let _ = sm.save_session(&session);
            // First-turn title: generate, persist, and announce so the
            // session list stays in sync.
            if session.title.is_none() {
                let first_user = session
                    .messages
                    .iter()
                    .find(|m| m.role == "user")
                    .map(|m| m.content.clone())
                    .unwrap_or_default();
                let title = if first_user.is_empty() {
                    String::from("Untitled chat")
                } else {
                    agent.generate_title(&first_user).await.unwrap_or_else(|_| {
                        first_user
                            .split_whitespace()
                            .take(6)
                            .collect::<Vec<_>>()
                            .join(" ")
                    })
                };
                let _ = sm.rename_session(&session_id, &title);
                done["title"] = json!(title);
                let _ = out_tx
                    .send(json!({
                        "type": "title_updated",
                        "session_id": session_id,
                        "title": title,
                    }))
                    .await;
            }
        }
        if out_tx.send(done).await.is_err() {
            return;
        }
        let _ = state.metrics.inc("ws_turns_total");
    });

    let _ = persist.await;
    let _ = forward_handle.await;
    chat.running = false;
}

/// Unused helper keeps `ToolError` referenced (error surface parity).
#[allow(unused)]
fn _tool_error_type(_: &ToolError) {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_ids_are_unique() {
        assert_ne!(request_id(), request_id());
    }

    #[test]
    fn resolve_pending_delivers_answer() {
        let (tx, _rx) = mpsc::channel(8);
        let pending = Arc::new(Mutex::new(HashMap::new()));
        let ask_user = SocketAskUser {
            tx,
            pending: pending.clone(),
        };
        let id = request_id();
        let (otx, orx) = oneshot::channel();
        pending.lock().expect("lock").insert(id.clone(), otx);
        resolve_pending(&ask_user, &id, Some(String::from("yes")));
        assert_eq!(orx.blocking_recv(), Ok(Some(String::from("yes"))));
        // Resolving an unknown id is a no-op.
        resolve_pending(&ask_user, "nope", None);
    }
}
