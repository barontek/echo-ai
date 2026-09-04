//! The agent: the LLM ↔ tool loop. Runs a conversation turn, executes
//! tool calls with safety approval, and streams progress events.
//!
//! One `Agent` is shared by a frontend but each `run` invocation owns
//! its working transcript; the agent itself is stateless between runs
//! (safe to call from a single task at a time — the same serialization
//! contract the original implementation enforced with its loop thread).
//!
//! Depends on: `tokio` (+ `tokio-util` cancellation), crate `llm`,
//! `safety`, `tools`, `session`, `change_tracker`.

use std::sync::Arc;
use std::time::Duration;

use serde_json::Value;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::change_tracker::ChangeTracker;
use crate::config::Config;
use crate::llm::provider::{
    self, ChatRequest, ChatResponse, LlmError, LlmMessage, LlmProvider, StreamEvent,
};
use crate::safety::SafetyConfig;
use crate::session::SessionManager;
use crate::tools::registry::Registry;
use crate::tools::tool::{AskUser, ToolContext};

/// Agent configuration (from `config.toml` + runtime wiring).
#[derive(Debug, Clone)]
pub struct AgentConfig {
    /// Model name for the configured provider.
    pub model: String,
    /// System prompt prepended to every run .
    pub system_prompt: String,
    /// Sampling temperature.
    pub temperature: f64,
    /// Context window for providers that support it.
    pub num_ctx: u32,
    /// Ollama keep-alive.
    pub keep_alive_secs: u64,
    /// Reasoning effort hint.
    pub effort: Option<String>,
    /// Per-request timeout.
    pub timeout: Duration,
    /// Maximum loop iterations.
    pub max_iterations: usize,
    /// Cap on tool-result text fed back to the model.
    pub max_tool_result_chars: usize,
    /// Context budgets.
    pub max_context_messages: usize,
    /// Context char budget.
    pub max_context_chars: usize,
}

impl From<&Config> for AgentConfig {
    fn from(cfg: &Config) -> Self {
        let effort = cfg.agent.effort.clone();
        Self {
            model: cfg.agent.model.clone(),
            system_prompt: cfg.agent.system_prompt.clone(),
            temperature: cfg.agent.temperature,
            num_ctx: cfg.ollama.num_ctx,
            keep_alive_secs: cfg.ollama.keep_alive_secs,
            effort: if effort.is_empty() || effort == "none" {
                None
            } else {
                Some(effort)
            },
            timeout: Duration::from_secs(cfg.agent.timeout_secs.max(1)),
            max_iterations: cfg.agent.max_iterations.max(1),
            max_tool_result_chars: cfg.agent.max_tool_result_chars,
            max_context_messages: cfg.agent.max_context_messages,
            max_context_chars: cfg.agent.max_context_chars,
        }
    }
}

/// Progress events streamed to the frontend.
#[derive(Debug, Clone)]
pub enum AgentEvent {
    /// A streamed text chunk (with optional thinking delta).
    Chunk {
        /// Visible text.
        content: String,
        /// Reasoning text delta.
        thinking: Option<String>,
    },
    /// A tool call is about to run.
    ToolStart {
        /// Tool name.
        name: String,
        /// JSON arguments.
        args: String,
    },
    /// A tool call finished.
    ToolEnd {
        /// Tool name.
        name: String,
        /// Whether execution succeeded.
        ok: bool,
        /// Result summary (truncated).
        summary: String,
    },
    /// The run failed.
    Error {
        /// Human-readable error.
        message: String,
    },
    /// The run finished.
    Done,
}

/// Outcome of a run.
#[derive(Debug)]
pub struct AgentResult {
    /// Final visible text.
    pub content: String,
    /// Reasoning text.
    pub thinking: Option<String>,
    /// The complete transcript (persist this).
    pub messages: Vec<LlmMessage>,
    /// Whether the iteration cap was hit without a final answer.
    pub hit_iteration_cap: bool,
}

/// Run failure modes.
#[derive(Debug, thiserror::Error)]
pub enum AgentError {
    /// The provider failed.
    #[error("llm: {0}")]
    Provider(#[from] LlmError),
    /// The run was cancelled.
    #[error("cancelled")]
    Cancelled,
}

/// The agent.
pub struct Agent {
    /// Provider.
    pub provider: Arc<dyn LlmProvider>,
    /// Tool registry.
    pub registry: Arc<Registry>,
    /// Agent settings.
    pub config: AgentConfig,
    /// Safety policy.
    pub safety: Arc<SafetyConfig>,
    /// Shared app config (tool context).
    pub app_config: Config,
    /// Session store slot (memory/sqlite tools). Shared with the server's
    /// `AppState` so a browser-driven setup can fill it after startup.
    pub session: Arc<std::sync::Mutex<Option<Arc<SessionManager>>>>,
    /// Change tracker (undo).
    pub tracker: Option<Arc<std::sync::Mutex<ChangeTracker>>>,
    /// Interactive question callback.
    pub ask_user: Option<Arc<dyn AskUser>>,
    /// Outbound HTTP client.
    pub http: Arc<dyn crate::llm::http::HttpClient>,
}

impl Agent {
    /// Runs one turn over `messages`, streaming events to `events`.
    ///
    /// The loop: call the provider; if it requests tools, run them (with
    /// approval when the safety policy requires it) and continue; stop
    /// on a final answer, an error, cancellation, or the iteration cap.
    /// A configured system prompt is prepended when the caller did not
    /// provide one.
    ///
    /// The length is inherent: one phase per loop iteration (stream the
    /// turn, run each tool call, feed results back) — the original implementation's
    /// `agent_run.c` had the same shape.
    ///
    /// # Errors
    /// `AgentError::Cancelled` when the token fires; `AgentError::Provider`
    /// when the provider fails before producing any output.
    #[allow(clippy::too_many_lines)] // one phase per loop iteration
    pub async fn run(
        &self,
        messages: Vec<LlmMessage>,
        events: mpsc::Sender<AgentEvent>,
        cancel: CancellationToken,
    ) -> Result<AgentResult, AgentError> {
        let mut messages = messages;
        let mut hit_iteration_cap = false;
        let mut final_response = ChatResponse::default();

        // Inject the configured system prompt when the caller did not
        // already provide one (compatible behavior).
        if !self.config.system_prompt.is_empty()
            && messages.first().map(|m| m.role.as_str()) != Some("system")
        {
            messages.insert(
                0,
                LlmMessage {
                    role: String::from("system"),
                    content: self.config.system_prompt.clone(),
                    tool_calls: Vec::new(),
                    tool_call_id: None,
                },
            );
        }

        for _ in 0..self.config.max_iterations {
            if cancel.is_cancelled() {
                return Err(AgentError::Cancelled);
            }

            // Keep the transcript inside the context budget.
            messages = crate::agent::context::trim_context(
                messages,
                self.config.max_context_messages,
                self.config.max_context_chars,
            );

            let request = ChatRequest {
                model: self.config.model.clone(),
                messages: messages.clone(),
                tools: self.registry.specs(),
                temperature: self.config.temperature,
                num_ctx: self.config.num_ctx,
                keep_alive_secs: self.config.keep_alive_secs,
                effort: self.config.effort.clone(),
            };

            let response = match self.stream_turn(&request, &events, &cancel).await {
                Ok(r) => r,
                Err(AgentError::Cancelled) => return Err(AgentError::Cancelled),
                Err(e) => {
                    let _ = events
                        .send(AgentEvent::Error {
                            message: e.to_string(),
                        })
                        .await;
                    return Err(e);
                }
            };

            if response.tool_calls.is_empty() {
                final_response = response;
                break;
            }

            // Execute the requested tools and feed results back.
            for call in &response.tool_calls {
                let name = call
                    .function
                    .as_ref()
                    .map(|f| f.name.clone())
                    .unwrap_or_default();
                let args: Value = call
                    .function
                    .as_ref()
                    .and_then(|f| f.arguments.as_ref())
                    .and_then(|a| serde_json::from_str(a).ok())
                    .unwrap_or(Value::Null);
                let output = self
                    .execute_tool(&name, args, call.id.clone(), &events)
                    .await;
                let (ok, summary) = match &output {
                    Ok(out) => (true, out.text.clone()),
                    Err(e) => (false, e.to_string()),
                };
                let _ = events
                    .send(AgentEvent::ToolEnd {
                        name: name.clone(),
                        ok,
                        summary: crate::utils::string_utils::ellipsize(&summary, 512),
                    })
                    .await;
                let tool_message = LlmMessage {
                    role: String::from("tool"),
                    content: summary,
                    tool_calls: Vec::new(),
                    tool_call_id: Some(call.id.clone().unwrap_or_default()),
                };
                messages.push(tool_message);
            }

            // Record the assistant message that requested the tools.
            messages.push(assistant_message(&response));
        }

        if final_response.content.is_empty() && final_response.tool_calls.is_empty() {
            hit_iteration_cap = true;
        }

        // The last assistant response that carried tool calls is already
        // in `messages`; ensure the final answer is too.
        if !hit_iteration_cap && !final_response.content.is_empty() {
            messages.push(assistant_message(&final_response));
        }

        let _ = events.send(AgentEvent::Done).await;
        Ok(AgentResult {
            content: final_response.content,
            thinking: final_response.thinking,
            messages,
            hit_iteration_cap,
        })
    }

    /// Streams one provider turn, forwarding events, cancelling on the
    /// token.
    async fn stream_turn(
        &self,
        request: &ChatRequest,
        events: &mpsc::Sender<AgentEvent>,
        cancel: &CancellationToken,
    ) -> Result<ChatResponse, AgentError> {
        let mut rx = tokio::select! {
            r = self.provider.clone().chat_stream(request) => r.map_err(AgentError::from)?,
            () = cancel.cancelled() => return Err(AgentError::Cancelled),
        };
        let mut response = ChatResponse::default();
        let mut calls: Vec<crate::agent::message::ToolCall> = Vec::new();

        loop {
            let event = tokio::select! {
                e = rx.recv() => e,
                () = cancel.cancelled() => return Err(AgentError::Cancelled),
            };
            let Some(event) = event else {
                break;
            };
            match event {
                StreamEvent::Chunk { content, thinking } => {
                    response.content.push_str(&content);
                    if let Some(t) = &thinking {
                        response
                            .thinking
                            .get_or_insert_with(String::new)
                            .push_str(t);
                    }
                    let _ = events.send(AgentEvent::Chunk { content, thinking }).await;
                }
                StreamEvent::ToolCallDelta {
                    index,
                    id,
                    name,
                    arguments,
                } => {
                    while calls.len() <= index {
                        calls.push(crate::agent::message::ToolCall {
                            id: None,
                            r#type: String::from("function"),
                            function: None,
                            result_content: None,
                            result_error: None,
                        });
                    }
                    let entry = calls[index].function.get_or_insert_with(|| {
                        crate::agent::message::Function {
                            name: String::new(),
                            arguments: Some(String::new()),
                        }
                    });
                    if entry.name.is_empty() {
                        entry.name = name.unwrap_or_default();
                    }
                    if let Some(a) = arguments {
                        entry.arguments.get_or_insert_with(String::new).push_str(&a);
                    }
                    if calls[index].id.is_none() {
                        calls[index].id = id;
                    }
                }
                StreamEvent::Done(done) => {
                    response = done;
                    response.tool_calls = if response.tool_calls.is_empty() {
                        calls
                    } else {
                        response.tool_calls
                    };
                    break;
                }
                StreamEvent::Error(e) => {
                    return Err(AgentError::Provider(LlmError::Protocol(e)));
                }
            }
        }
        Ok(response)
    }

    /// Runs one tool call with safety approval and a fresh
    /// `ToolContext`.
    async fn execute_tool(
        &self,
        name: &str,
        args: Value,
        call_id: Option<String>,
        events: &mpsc::Sender<AgentEvent>,
    ) -> std::result::Result<crate::tools::tool::ToolOutput, crate::tools::tool::ToolError> {
        let Some(tool) = self.registry.get(name) else {
            return Err(crate::tools::tool::ToolError::InvalidArgs(format!(
                "no such tool: {name}"
            )));
        };

        // Approval gate: the destructive-command screen applies to
        // command-carrying tools.
        let command = args
            .get("command")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let needs_approval = self.safety.needs_approval_for_command(name, command);

        if needs_approval {
            let Some(ask) = &self.ask_user else {
                return Err(crate::tools::tool::ToolError::Safety(format!(
                    "{name} requires approval but no interactive user is available"
                )));
            };
            let _ = events
                .send(AgentEvent::ToolStart {
                    name: String::from(name),
                    args: args.to_string(),
                })
                .await;
            match ask.ask_approval(name, &args.to_string()).await {
                Ok(Some(answer))
                    if answer.trim().eq_ignore_ascii_case("yes") || answer.trim() == "y" => {}
                Ok(_) => {
                    return Err(crate::tools::tool::ToolError::Cancelled);
                }
                Err(e) => {
                    return Err(crate::tools::tool::ToolError::Execution(e.to_string()));
                }
            }
        }

        let _ = events
            .send(AgentEvent::ToolStart {
                name: String::from(name),
                args: args.to_string(),
            })
            .await;

        // The session slot is shared with the server's AppState; a poisoned
        // lock is an invariant violation (fail fast).
        #[allow(clippy::expect_used)] // poisoned slot lock = invariant violation
        let ctx_session = self
            .session
            .lock()
            .expect("session slot lock poisoned")
            .clone();
        let ctx = ToolContext {
            safety: &self.safety,
            config: &self.app_config,
            session: ctx_session.as_deref(),
            change_tracker: self.tracker.as_ref(),
            ask_user: self.ask_user.clone(),
            http: self.http.clone(),
        };
        let output = tool.execute(args, &ctx).await?;

        // Cap the result text before feeding it back to the model.
        let mut capped = output;
        if capped.text.chars().count() > self.config.max_tool_result_chars {
            let _ = call_id;
            capped.text = crate::utils::string_utils::ellipsize(
                &capped.text,
                self.config.max_tool_result_chars,
            );
        }
        Ok(capped)
    }

    /// Generates a session title from the first user message.
    ///
    /// # Errors
    /// `LlmError` when the provider call fails.
    pub async fn generate_title(&self, first_user_message: &str) -> Result<String, LlmError> {
        let request = ChatRequest {
            model: self.config.model.clone(),
            messages: vec![
                LlmMessage {
                    role: String::from("system"),
                    content: String::from(
                        "Write a short title (max 6 words, no quotes, no markdown) for this chat.",
                    ),
                    tool_calls: Vec::new(),
                    tool_call_id: None,
                },
                LlmMessage {
                    role: String::from("user"),
                    content: String::from(first_user_message),
                    tool_calls: Vec::new(),
                    tool_call_id: None,
                },
            ],
            tools: Vec::new(),
            temperature: 0.2,
            num_ctx: self.config.num_ctx,
            keep_alive_secs: self.config.keep_alive_secs,
            effort: None,
        };
        let response = self.provider.clone().chat(&request).await?;
        let mut title = response.content.trim().to_string();
        title = title.trim_start_matches("Title:").trim().to_string();
        title = title.trim_matches('"').trim().to_string();
        if title.len() > 60 {
            title = crate::utils::string_utils::ellipsize(&title, 60);
        }
        if title.is_empty() {
            title = String::from("Untitled chat");
        }
        Ok(title)
    }
}

/// Converts a provider response into an assistant message.
fn assistant_message(response: &ChatResponse) -> LlmMessage {
    LlmMessage {
        role: String::from("assistant"),
        content: response.content.clone(),
        tool_calls: response.tool_calls.clone(),
        tool_call_id: None,
    }
}

/// Convenience: drives [`Agent::run`] with a timeout and no events.
///
/// # Errors
/// Propagates `AgentError`.
pub async fn run_silent(
    agent: &Agent,
    messages: Vec<LlmMessage>,
    timeout: Duration,
) -> Result<AgentResult, AgentError> {
    let (tx, _rx) = mpsc::channel(64);
    let cancel = CancellationToken::new();
    tokio::select! {
        r = agent.run(messages, tx, cancel.clone()) => r,
        () = tokio::time::sleep(timeout) => {
            cancel.cancel();
            Err(AgentError::Cancelled)
        }
    }
}

/// Re-export of the stream collector for frontends that want the plain
/// response (used by tests).
pub use provider::collect_stream;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn agent_config_from_toml() {
        let cfg = Config::default();
        let ac = AgentConfig::from(&cfg);
        assert_eq!(ac.model, "");
        assert!((ac.temperature - 0.7).abs() < f64::EPSILON);
        assert_eq!(ac.effort.as_deref(), Some("medium"));
        assert_eq!(ac.max_iterations, 20);
    }
}
