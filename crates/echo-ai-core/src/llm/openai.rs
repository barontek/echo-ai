//! `OpenAI` (`Codex`) provider: the `/v1/responses` API, OAuth-token
//! authenticated, with SSE streaming.
//!
//! Token lives in the session store's OAuth vault (never in config).
//! Stream deltas carry text; the final `response.completed` event
//! carries the full output which is parsed like a non-streamed
//! response.
//!
//! Depends on: `serde_json`, `tokio`, crate `llm::{http,provider}`.

use futures_util::future::BoxFuture;
use serde_json::{Value, json};

use super::http::HttpClient;
use super::provider::{
    ChatRequest, ChatResponse, LlmError, LlmMessage, LlmProvider, StreamEvent, ToolSpec,
};

/// The Codex provider.
#[derive(Clone)]
pub struct OpenAi {
    token: String,
    http: std::sync::Arc<dyn HttpClient>,
}

impl OpenAi {
    /// Creates a provider authenticated with an OAuth bearer token.
    pub fn new(token: String, http: std::sync::Arc<dyn HttpClient>) -> Self {
        Self { token, http }
    }

    fn headers(&self) -> Vec<(&'static str, String)> {
        vec![
            ("Authorization", format!("Bearer {}", self.token)),
            ("Content-Type", String::from("application/json")),
        ]
    }
}

impl LlmProvider for OpenAi {
    fn name(&self) -> &'static str {
        "openai"
    }

    fn supports_effort(&self) -> bool {
        true
    }

    fn chat(
        self: std::sync::Arc<Self>,
        req: &ChatRequest,
    ) -> BoxFuture<'static, Result<ChatResponse, LlmError>> {
        let this = self.clone();
        let req = req.clone();
        Box::pin(async move { this.chat_impl(&req).await })
    }

    fn chat_stream(
        self: std::sync::Arc<Self>,
        req: &ChatRequest,
    ) -> BoxFuture<'static, Result<tokio::sync::mpsc::Receiver<StreamEvent>, LlmError>> {
        let this = self.clone();
        let req = req.clone();
        Box::pin(async move { this.chat_stream_impl(&req).await })
    }
}

impl OpenAi {
    async fn chat_impl(&self, req: &ChatRequest) -> Result<ChatResponse, LlmError> {
        let owned = self.headers();
        let headers: Vec<(&str, &str)> = owned.iter().map(|(k, v)| (*k, v.as_str())).collect();
        let body = build_responses_body(req, false);
        let json = self
            .http
            .post_json("https://api.openai.com/v1/responses", &headers, body)
            .await?;
        parse_responses_response(&json)
    }

    async fn chat_stream_impl(
        &self,
        req: &ChatRequest,
    ) -> Result<tokio::sync::mpsc::Receiver<StreamEvent>, LlmError> {
        let owned = self.headers();
        let headers: Vec<(&str, &str)> = owned.iter().map(|(k, v)| (*k, v.as_str())).collect();
        let body = build_responses_body(req, true);
        let mut lines = self
            .http
            .post_stream("https://api.openai.com/v1/responses", &headers, body)
            .await?;
        let (tx, rx) = tokio::sync::mpsc::channel(64);
        tokio::spawn(async move {
            let mut response = ChatResponse::default();
            while let Some(line) = lines.recv().await {
                match line {
                    Ok(l) => match parse_stream_line(&l, &mut response) {
                        Ok(Some(event)) => {
                            let done = matches!(event, StreamEvent::Done(_));
                            if tx.send(event).await.is_err() {
                                return;
                            }
                            if done {
                                return;
                            }
                        }
                        Ok(None) => {}
                        Err(e) => {
                            let _ = tx.send(StreamEvent::Error(e.to_string())).await;
                            return;
                        }
                    },
                    Err(e) => {
                        let _ = tx.send(StreamEvent::Error(e.to_string())).await;
                        return;
                    }
                }
            }
            let _ = tx.send(StreamEvent::Done(response)).await;
        });
        Ok(rx)
    }
}

/// Builds the `/v1/responses` request body.
pub fn build_responses_body(req: &ChatRequest, stream: bool) -> Value {
    let mut body = json!({
        "model": req.model,
        "input": req.messages.iter().map(responses_input).collect::<Vec<_>>(),
        "tools": req.tools.iter().map(tool_spec).collect::<Vec<_>>(),
        "stream": stream,
        "temperature": req.temperature,
    });
    if let Some(effort) = &req.effort
        && !effort.is_empty()
        && effort != "none"
    {
        body["reasoning"] = json!({ "effort": effort });
    }
    body
}

fn responses_input(m: &LlmMessage) -> Value {
    let mut item = json!({
        "role": m.role,
        "content": m.content,
    });
    if let Some(id) = &m.tool_call_id {
        item["tool_call_id"] = json!(id);
    }
    if !m.tool_calls.is_empty() {
        item["tool_calls"] = json!(
            m.tool_calls
                .iter()
                .map(|tc| json!({
                    "id": tc.id.clone().unwrap_or_default(),
                    "type": "function_call",
                    "name": tc.function.as_ref().map(|f| f.name.clone()).unwrap_or_default(),
                    "arguments": tc.function.as_ref()
                        .and_then(|f| f.arguments.as_ref())
                        .cloned()
                        .unwrap_or_else(|| String::from("{}")),
                }))
                .collect::<Vec<_>>()
        );
    }
    item
}

fn tool_spec(t: &ToolSpec) -> Value {
    json!({
        "type": "function",
        "name": t.name,
        "description": t.description,
        "parameters": t.parameters,
    })
}

/// Parses a non-streamed `/v1/responses` response.
///
/// # Errors
/// `LlmError::Protocol` when the output structure is unexpected.
pub fn parse_responses_response(json: &Value) -> Result<ChatResponse, LlmError> {
    let mut response = ChatResponse {
        finish_reason: json
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("completed")
            .to_string(),
        ..Default::default()
    };
    let Some(output) = json.get("output").and_then(Value::as_array) else {
        return Ok(response);
    };
    for item in output {
        match item.get("type").and_then(Value::as_str) {
            Some("message") => {
                for part in item
                    .get("content")
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
                {
                    if let Some(text) = part.get("text").and_then(Value::as_str) {
                        response.content.push_str(text);
                    }
                }
            }
            Some("function_call") => {
                response.tool_calls.push(crate::agent::message::ToolCall {
                    id: item
                        .get("call_id")
                        .and_then(Value::as_str)
                        .map(String::from),
                    r#type: String::from("function"),
                    function: Some(crate::agent::message::Function {
                        name: item
                            .get("name")
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .to_string(),
                        arguments: item
                            .get("arguments")
                            .and_then(Value::as_str)
                            .map(String::from),
                    }),
                    result_content: None,
                    result_error: None,
                });
            }
            _ => {}
        }
    }
    // Reasoning text arrives in the `reasoning` array.
    for r in json
        .get("reasoning")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        for part in r
            .get("content")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            if let Some(text) = part.get("text").and_then(Value::as_str) {
                response
                    .thinking
                    .get_or_insert_with(String::new)
                    .push_str(text);
            }
        }
    }
    Ok(response)
}

/// Parses one `SSE` line of a streaming response.
///
/// # Errors
/// `LlmError::Protocol` when the event is a provider failure or
/// malformed `SSE`.
pub fn parse_stream_line(
    line: &str,
    response: &mut ChatResponse,
) -> Result<Option<StreamEvent>, LlmError> {
    let line = line.trim();
    if line.is_empty() {
        return Ok(None);
    }
    let Some(payload) = line.strip_prefix("data:") else {
        return Ok(None);
    };
    let payload = payload.trim();
    if payload == "[DONE]" {
        return Ok(Some(StreamEvent::Done(response.clone())));
    }
    let v: Value = serde_json::from_str(payload)
        .map_err(|e| LlmError::Protocol(format!("bad SSE: {e}: {line}")))?;
    let event_type = v.get("type").and_then(Value::as_str).unwrap_or("");
    match event_type {
        "response.output_text.delta" => {
            let delta = v.get("delta").and_then(Value::as_str).unwrap_or_default();
            response.content.push_str(delta);
            Ok(Some(StreamEvent::Chunk {
                content: String::from(delta),
                thinking: None,
            }))
        }
        "response.reasoning_summary_text.delta" | "response.reasoning_text.delta" => {
            let delta = v.get("delta").and_then(Value::as_str).unwrap_or_default();
            response
                .thinking
                .get_or_insert_with(String::new)
                .push_str(delta);
            Ok(Some(StreamEvent::Chunk {
                content: String::new(),
                thinking: Some(String::from(delta)),
            }))
        }
        "response.completed" => {
            let full = v.get("response").cloned().unwrap_or(Value::Null);
            let parsed = parse_responses_response(&full)?;
            *response = parsed.clone();
            Ok(Some(StreamEvent::Done(parsed)))
        }
        "response.failed" | "error" => {
            let msg = v.get("error").map_or_else(
                || String::from("provider reported failure"),
                |e| {
                    if e.is_string() {
                        e.as_str().unwrap_or("").to_string()
                    } else {
                        e.get("message")
                            .and_then(Value::as_str)
                            .unwrap_or("")
                            .to_string()
                    }
                },
            );
            Err(LlmError::Protocol(msg))
        }
        _ => Ok(None),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn req() -> ChatRequest {
        ChatRequest {
            model: String::from("gpt-5-codex"),
            messages: vec![LlmMessage {
                role: String::from("user"),
                content: String::from("hi"),
                tool_calls: Vec::new(),
                tool_call_id: None,
            }],
            tools: vec![ToolSpec {
                name: String::from("read_file"),
                description: String::from("read"),
                parameters: json!({"type": "object"}),
            }],
            effort: Some(String::from("high")),
            ..Default::default()
        }
    }

    #[test]
    fn body_includes_reasoning_effort() {
        let body = build_responses_body(&req(), false);
        assert_eq!(body["model"], "gpt-5-codex");
        assert_eq!(body["reasoning"]["effort"], "high");
        assert_eq!(body["tools"][0]["type"], "function");
    }

    #[test]
    fn non_stream_response_parses_output() {
        let json = json!({
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "hello"}]},
                {"type": "function_call", "call_id": "fc_1", "name": "read_file", "arguments": "{\"path\":\"x\"}"}
            ],
            "reasoning": [{"content": [{"type": "output_text", "text": "thinking..."}]}]
        });
        let r = parse_responses_response(&json).expect("parse");
        assert_eq!(r.content, "hello");
        assert_eq!(r.thinking.as_deref(), Some("thinking..."));
        assert_eq!(r.tool_calls.len(), 1);
        assert_eq!(r.tool_calls[0].id.as_deref(), Some("fc_1"));
    }

    #[test]
    fn stream_completed_event_replaces_response() {
        let mut response = ChatResponse::default();
        let line = r#"data: {"type":"response.output_text.delta","delta":"hi"}"#;
        let ev = parse_stream_line(line, &mut response).expect("delta");
        assert!(matches!(ev, Some(StreamEvent::Chunk { .. })));
        assert_eq!(response.content, "hi");

        let done_line = r#"data: {"type":"response.completed","response":{"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"final"}]}]}}"#;
        let ev = parse_stream_line(done_line, &mut response).expect("done");
        match ev {
            Some(StreamEvent::Done(done)) => assert_eq!(done.content, "final"),
            other => panic!("expected Done, got {other:?}"),
        }
        assert_eq!(response.content, "final");
    }

    #[test]
    fn stream_failure_is_protocol_error() {
        let mut response = ChatResponse::default();
        let line = r#"data: {"type":"response.failed","error":{"message":"boom"}}"#;
        let err = parse_stream_line(line, &mut response).expect_err("failed event");
        assert!(err.to_string().contains("boom"));
    }
}
