//! The `LlmProvider` contract: request/response types and the trait.
//!
//! This module defines the shared contract only (the C version's
//! `provider.h` — the documented exception to one-module-per-file; the
//! implementations live in their own files).
//!
//! Depends on: `serde_json`, `tokio`, crate `agent::message`.

use futures_util::future::BoxFuture;
use serde::Deserialize;
use serde_json::Value;

use crate::agent::message::ToolCall;
use crate::error::Error;

/// A message sent to a provider (provider-agnostic shape).
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct LlmMessage {
    /// `system`, `user`, `assistant`, or `tool`.
    pub role: String,
    /// Text content.
    #[serde(default)]
    pub content: String,
    /// Tool invocations (assistant messages).
    #[serde(default)]
    pub tool_calls: Vec<ToolCall>,
    /// Which tool call this answers (tool messages).
    #[serde(default)]
    pub tool_call_id: Option<String>,
}

/// A tool the model may invoke, with its JSON schema.
#[derive(Debug, Clone)]
pub struct ToolSpec {
    /// Tool name as registered.
    pub name: String,
    /// One-line description.
    pub description: String,
    /// JSON-schema parameters.
    pub parameters: Value,
}

/// A non-streaming completion request.
#[derive(Debug, Clone)]
pub struct ChatRequest {
    /// Model name.
    pub model: String,
    /// Conversation.
    pub messages: Vec<LlmMessage>,
    /// Available tools.
    pub tools: Vec<ToolSpec>,
    /// Sampling temperature.
    pub temperature: f64,
    /// Context window (providers that support it).
    pub num_ctx: u32,
    /// Ollama keep-alive seconds.
    pub keep_alive_secs: u64,
    /// Reasoning effort hint.
    pub effort: Option<String>,
}

impl Default for ChatRequest {
    fn default() -> Self {
        Self {
            model: String::new(),
            messages: Vec::new(),
            tools: Vec::new(),
            temperature: 0.7,
            num_ctx: 4096,
            keep_alive_secs: 120,
            effort: None,
        }
    }
}

/// A completed (non-streamed) response.
#[derive(Debug, Clone, Default)]
pub struct ChatResponse {
    /// Final visible text.
    pub content: String,
    /// Reasoning text when the provider separates it.
    pub thinking: Option<String>,
    /// Tool invocations requested by the model.
    pub tool_calls: Vec<ToolCall>,
    /// Provider's finish reason (`stop`, `tool_calls`, ...).
    pub finish_reason: String,
}

/// Streaming events for one turn.
#[derive(Debug, Clone)]
pub enum StreamEvent {
    /// A text chunk (may carry a thinking fragment).
    Chunk {
        /// Visible text delta.
        content: String,
        /// Reasoning delta.
        thinking: Option<String>,
    },
    /// Tool-call delta (accumulate until done).
    ToolCallDelta {
        /// Zero-based index in the call list.
        index: usize,
        /// Call id when the provider sends it (usually first delta).
        id: Option<String>,
        /// Function name delta.
        name: Option<String>,
        /// Arguments-string delta (concatenate).
        arguments: Option<String>,
    },
    /// Turn finished (with the assembled response).
    Done(ChatResponse),
    /// Transport or protocol failure mid-stream.
    Error(String),
}

/// Provider error (thiserror; surfaced as `Error::Session`-style
/// variants at the agent boundary via conversion).
#[derive(Debug, thiserror::Error)]
pub enum LlmError {
    /// Request failed before any response.
    #[error("llm request failed: {0}")]
    Transport(String),
    /// The provider returned a non-success status.
    #[error("llm http {status}: {body}")]
    Http {
        /// Status code.
        status: u16,
        /// Response body fragment.
        body: String,
    },
    /// The response body did not match the expected protocol.
    #[error("llm protocol error: {0}")]
    Protocol(String),
}

impl From<LlmError> for Error {
    fn from(e: LlmError) -> Self {
        Error::Session(format!("llm: {e}"))
    }
}

/// The provider contract. All methods are cancellable by dropping the
/// task or the returned receiver. Methods take `self: Arc<Self>` so the
/// returned futures are `'static` and the trait stays dyn-compatible
/// (registries hold `Arc<dyn LlmProvider>`).
pub trait LlmProvider: Send + Sync {
    /// Provider catalog name (`ollama`, `openai`, ...).
    fn name(&self) -> &'static str;

    /// One complete, non-streamed turn.
    ///
    /// # Errors
    /// `LlmError::Transport`/`LlmError::Http`/`LlmError::Protocol`.
    fn chat(
        self: std::sync::Arc<Self>,
        req: &ChatRequest,
    ) -> BoxFuture<'static, Result<ChatResponse, LlmError>>;

    /// One streamed turn. The receiver yields [`StreamEvent`]s until
    /// `Done` or `Error`; dropping the receiver cancels the request.
    ///
    /// # Errors
    /// Fails only before the stream starts.
    fn chat_stream(
        self: std::sync::Arc<Self>,
        req: &ChatRequest,
    ) -> BoxFuture<'static, Result<tokio::sync::mpsc::Receiver<StreamEvent>, LlmError>>;

    /// Whether this provider accepts a reasoning-effort hint.
    fn supports_effort(&self) -> bool {
        false
    }
}

/// Converts a [`StreamEvent`] stream into a complete response,
/// assembling tool-call deltas. Used by callers that only need the
/// final answer.
///
/// # Errors
/// `LlmError::Protocol` when the stream ends without `Done` or ends on
/// `Error`.
pub async fn collect_stream(
    mut rx: tokio::sync::mpsc::Receiver<StreamEvent>,
) -> Result<ChatResponse, LlmError> {
    let mut response = ChatResponse::default();
    let mut deltas: Vec<Option<(Option<String>, Vec<u8>)>> = Vec::new();
    while let Some(event) = rx.recv().await {
        match event {
            StreamEvent::Chunk { content, thinking } => {
                response.content.push_str(&content);
                if let Some(t) = thinking {
                    response
                        .thinking
                        .get_or_insert_with(String::new)
                        .push_str(&t);
                }
            }
            StreamEvent::ToolCallDelta {
                index,
                id,
                name,
                arguments,
            } => {
                while deltas.len() <= index {
                    deltas.push(None);
                }
                let entry = deltas[index].get_or_insert_with(|| (None, Vec::new()));
                if entry.0.is_none() {
                    entry.0 = id;
                }
                if let Some(n) = name {
                    // Name arrives in the first delta of a call; later
                    // deltas only carry arguments.
                    if entry.0.is_none() {
                        entry.0 = Some(n);
                    }
                }
                if let Some(a) = arguments {
                    entry.1.extend_from_slice(a.as_bytes());
                }
            }
            StreamEvent::Done(done) => {
                response.finish_reason = done.finish_reason;
                if response.content.is_empty() {
                    response.content = done.content;
                }
                if response.thinking.is_none() {
                    response.thinking = done.thinking;
                }
                response.tool_calls = done.tool_calls;
                return Ok(response);
            }
            StreamEvent::Error(e) => return Err(LlmError::Protocol(e)),
        }
    }
    Err(LlmError::Protocol(String::from(
        "stream ended without a Done event",
    )))
}
