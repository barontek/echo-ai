//! The `Tool` contract: what a tool is, what it returns, and what the
//! execution context provides.
//!
//! Mirrors the C project's `tool.h` vtable contract; per-tool contracts
//! live in each tool's module docs.
//!
//! Depends on: `serde_json`, `tokio`, `futures-util`, crate `config`,
//! `error`, `safety`, `session`, `change_tracker`, `llm::http`.

use futures_util::future::BoxFuture;
use serde_json::Value;
use std::sync::Arc;

use crate::change_tracker::ChangeTracker;
use crate::config::Config;
use crate::error::{Error, Result};
use crate::llm::http::HttpClient;
use crate::safety::SafetyConfig;
use crate::session::SessionManager;

/// Ask-the-user callback (interactive approvals and questions).
pub trait AskUser: Send + Sync {
    /// Asks `prompt` and returns the answer; `None` means cancelled or
    /// timed out.
    fn ask(&self, prompt: &str) -> BoxFuture<'_, Result<Option<String>>>;

    /// Asks for approval of a specific tool invocation. The default
    /// implementation formats the tool + arguments into a prompt and
    /// delegates to [`Self::ask`]; frontends that distinguish approval
    /// dialogs from freeform questions override this.
    fn ask_approval(&self, tool: &str, args: &str) -> BoxFuture<'_, Result<Option<String>>> {
        let prompt = format!(
            "Approve running the `{tool}` tool with arguments:\n\n{args}\n\nReply yes to approve."
        );
        self.ask(&prompt)
    }
}

/// Everything a tool may need during execution.
pub struct ToolContext<'a> {
    /// Effective safety policy (workspace pinning, caps).
    pub safety: &'a SafetyConfig,
    /// The loaded configuration.
    pub config: &'a Config,
    /// Session store, when persistence is enabled.
    pub session: Option<&'a SessionManager>,
    /// Undo/redo tracker (writes snapshot before modifying files).
    pub change_tracker: Option<&'a Arc<std::sync::Mutex<ChangeTracker>>>,
    /// Interactive question callback (may be absent in headless mode).
    pub ask_user: Option<Arc<dyn AskUser>>,
    /// Shared outbound HTTP client.
    pub http: Arc<dyn HttpClient>,
}

/// The result of a tool execution.
#[derive(Debug, Clone)]
pub struct ToolOutput {
    /// Human-readable result text (fed back to the model).
    pub text: String,
    /// Structured payload for tools that produce one.
    pub structured: Option<Value>,
}

impl ToolOutput {
    /// A plain text result.
    pub fn text(text: impl Into<String>) -> Self {
        Self {
            text: text.into(),
            structured: None,
        }
    }

    /// A result with a structured payload plus text.
    pub fn structured(text: impl Into<String>, value: Value) -> Self {
        Self {
            text: text.into(),
            structured: Some(value),
        }
    }
}

/// Tool execution failure.
#[derive(Debug, thiserror::Error)]
pub enum ToolError {
    /// Arguments failed validation.
    #[error("invalid arguments: {0}")]
    InvalidArgs(String),
    /// Safety policy rejected the operation.
    #[error("safety: {0}")]
    Safety(String),
    /// I/O failure with path context.
    #[error("io on {path}: {source}")]
    Io {
        /// The path involved.
        path: std::path::PathBuf,
        /// The underlying error.
        #[source]
        source: std::io::Error,
    },
    /// Execution failed (subprocess, network, ...).
    #[error("execution failed: {0}")]
    Execution(String),
    /// The operation hit its time limit.
    #[error("timed out after {0:?}")]
    Timeout(std::time::Duration),
    /// The user cancelled / did not answer.
    #[error("cancelled")]
    Cancelled,
}

impl From<ToolError> for Error {
    fn from(e: ToolError) -> Self {
        Error::Session(format!("tool: {e}"))
    }
}

/// A built-in tool.
pub trait Tool: Send + Sync {
    /// Registry name (matches provider tool names).
    fn name(&self) -> &'static str;

    /// One-line description for the model.
    fn description(&self) -> &'static str;

    /// JSON-schema parameters object.
    fn parameters(&self) -> Value;

    /// Executes the tool with parsed `args`. The returned future is
    /// tied to the context's lifetime.
    ///
    /// # Errors
    /// `ToolError` variants per tool contract; the agent loop converts
    /// failures into tool messages (recorded, never aborting).
    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>>;
}

/// Arguments helper: extract a string arg, rejecting missing/invalid.
///
/// # Errors
/// `ToolError::InvalidArgs` when `name` is absent or not a string.
pub fn arg_string(args: &Value, name: &str) -> std::result::Result<String, ToolError> {
    args.get(name)
        .and_then(Value::as_str)
        .map(String::from)
        .ok_or_else(|| ToolError::InvalidArgs(format!("missing or non-string `{name}`")))
}

/// Arguments helper: extract an optional string arg.
pub fn arg_optional_string(args: &Value, name: &str) -> Option<String> {
    args.get(name).and_then(Value::as_str).map(String::from)
}

/// Arguments helper: extract an optional bool arg.
pub fn arg_optional_bool(args: &Value, name: &str) -> Option<bool> {
    args.get(name).and_then(Value::as_bool)
}

/// Arguments helper: extract an optional u64 arg.
pub fn arg_optional_u64(args: &Value, name: &str) -> Option<u64> {
    args.get(name).and_then(Value::as_u64)
}
