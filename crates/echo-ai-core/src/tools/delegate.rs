//! The delegate tool: run a sub-agent task or sub-query through the LLM provider.
//!
//! Mirrors the original implementation's `tool_delegate.c`: delegates a scoped sub-task
//! to a secondary LLM query with its own prompt context, isolating intermediate steps
//! from the primary conversation transcript.
//!
//! Depends on: `serde_json`, crate `llm::provider`, `tools::tool`.

use std::sync::Arc;

use futures_util::future::BoxFuture;
use serde_json::{Value, json};

use super::tool::{Tool, ToolContext, ToolError, ToolOutput, arg_string};
use crate::llm::provider::{ChatRequest, LlmMessage, LlmProvider};

/// The delegate tool: runs an isolated sub-task turn against an LLM provider.
pub struct Delegate {
    provider: Arc<dyn LlmProvider>,
    model: String,
}

impl Delegate {
    /// Creates a new delegate tool using the given LLM provider and model name.
    #[must_use]
    pub fn new(provider: Arc<dyn LlmProvider>, model: String) -> Self {
        Self { provider, model }
    }
}

impl Tool for Delegate {
    fn name(&self) -> &'static str {
        "delegate"
    }

    fn description(&self) -> &'static str {
        "Delegates a sub-task or focused question to a sub-agent, returning the final answer."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The specific sub-task or question to delegate to the sub-agent"
                }
            },
            "required": ["task"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        _ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        let provider = Arc::clone(&self.provider);
        let model = self.model.clone();
        Box::pin(async move {
            let task = arg_string(&args, "task")?;
            let request = ChatRequest {
                model,
                messages: vec![
                    LlmMessage {
                        role: String::from("system"),
                        content: String::from(
                            "You are a focused sub-agent assistant. Solve the assigned sub-task directly, accurately, and concisely.",
                        ),
                        tool_calls: Vec::new(),
                        tool_call_id: None,
                    },
                    LlmMessage {
                        role: String::from("user"),
                        content: task,
                        tool_calls: Vec::new(),
                        tool_call_id: None,
                    },
                ],
                tools: Vec::new(),
                temperature: 0.2,
                num_ctx: 4096,
                keep_alive_secs: 300,
                effort: None,
                session_id: None,
            };

            let response = provider
                .chat(&request)
                .await
                .map_err(|e| ToolError::Execution(format!("delegate LLM error: {e}")))?;

            Ok(ToolOutput::text(response.content))
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::Config;
    use crate::llm::http::ReqwestClient;
    use crate::llm::provider::{ChatResponse, LlmError, StreamEvent};
    use crate::safety::SafetyConfig;
    use tokio::sync::mpsc;

    struct MockProvider {
        reply: String,
    }

    impl LlmProvider for MockProvider {
        fn name(&self) -> &'static str {
            "mock"
        }

        fn chat(
            self: Arc<Self>,
            _req: &ChatRequest,
        ) -> BoxFuture<'static, std::result::Result<ChatResponse, LlmError>> {
            let reply = self.reply.clone();
            Box::pin(async move {
                Ok(ChatResponse {
                    content: reply,
                    thinking: None,
                    tool_calls: Vec::new(),
                    finish_reason: String::from("stop"),
                })
            })
        }

        fn chat_stream(
            self: Arc<Self>,
            _req: &ChatRequest,
        ) -> BoxFuture<'static, std::result::Result<mpsc::Receiver<StreamEvent>, LlmError>>
        {
            Box::pin(async move {
                let (_tx, rx) = mpsc::channel(1);
                Ok(rx)
            })
        }
    }

    #[tokio::test]
    async fn delegate_name_and_schema() {
        let mock = Arc::new(MockProvider {
            reply: String::from("sub-task done"),
        });
        let tool = Delegate::new(mock, String::from("mock-model"));
        assert_eq!(tool.name(), "delegate");
        let schema = tool.parameters();
        assert!(schema["properties"]["task"].is_object());
    }

    #[tokio::test]
    async fn delegate_executes_and_returns_result() {
        let mock = Arc::new(MockProvider {
            reply: String::from("sub-task complete: result is 42"),
        });
        let tool = Delegate::new(mock, String::from("mock-model"));
        let safety = SafetyConfig::from_config(&Config::default().safety, None);
        let config = Config::default();
        let http = Arc::new(ReqwestClient::new());
        let ctx = ToolContext {
            safety: &safety,
            config: &config,
            session: None,
            change_tracker: None,
            ask_user: None,
            http,
        };

        let output = tool
            .execute(json!({ "task": "calculate 40 + 2" }), &ctx)
            .await
            .expect("execute");
        assert_eq!(output.text, "sub-task complete: result is 42");
    }

    #[tokio::test]
    async fn delegate_missing_task_errors() {
        let mock = Arc::new(MockProvider {
            reply: String::new(),
        });
        let tool = Delegate::new(mock, String::from("mock-model"));
        let safety = SafetyConfig::from_config(&Config::default().safety, None);
        let config = Config::default();
        let http = Arc::new(ReqwestClient::new());
        let ctx = ToolContext {
            safety: &safety,
            config: &config,
            session: None,
            change_tracker: None,
            ask_user: None,
            http,
        };

        let err = tool.execute(json!({}), &ctx).await.unwrap_err();
        assert!(matches!(err, ToolError::InvalidArgs(_)));
    }
}
