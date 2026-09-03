//! Ollama provider: `/api/chat`, streaming via newline-delimited JSON.
//!
//! The request-body builder and the NDJSON line parser are pure
//! functions so the wire format is unit-testable without a server; the
//! provider itself is a thin async shell over them.
//!
//! Depends on: `serde_json`, `tokio`, crate `llm::{http,provider}`.

use futures_util::future::BoxFuture;
use serde_json::{Value, json};

use super::http::HttpClient;
use super::provider::{
    ChatRequest, ChatResponse, LlmError, LlmMessage, LlmProvider, StreamEvent, ToolSpec,
};

/// The Ollama provider.
#[derive(Clone)]
pub struct Ollama {
    base_url: String,
    http: std::sync::Arc<dyn HttpClient>,
}

impl Ollama {
    /// Creates a provider against `base_url` (e.g.
    /// `http://localhost:11434`).
    pub fn new(base_url: String, http: std::sync::Arc<dyn HttpClient>) -> Self {
        Self { base_url, http }
    }
}

impl LlmProvider for Ollama {
    fn name(&self) -> &'static str {
        "ollama"
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

impl Ollama {
    async fn chat_impl(&self, req: &ChatRequest) -> Result<ChatResponse, LlmError> {
        let body = build_chat_body(req, false);
        let url = format!("{}/api/chat", self.base_url.trim_end_matches('/'));
        let json = self.http.post_json(&url, &[], body).await?;
        parse_chat_response(&json)
    }

    async fn chat_stream_impl(
        &self,
        req: &ChatRequest,
    ) -> Result<tokio::sync::mpsc::Receiver<StreamEvent>, LlmError> {
        let body = build_chat_body(req, true);
        let url = format!("{}/api/chat", self.base_url.trim_end_matches('/'));
        let mut lines = self.http.post_stream(&url, &[], body).await?;
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

/// Builds the `/api/chat` request body.
pub fn build_chat_body(req: &ChatRequest, stream: bool) -> Value {
    json!({
        "model": req.model,
        "messages": req.messages.iter().map(llm_message).collect::<Vec<_>>(),
        "tools": req.tools.iter().map(tool_spec).collect::<Vec<_>>(),
        "stream": stream,
        "options": {
            "temperature": req.temperature,
            "num_ctx": req.num_ctx,
        },
        "keep_alive": req.keep_alive_secs,
    })
}

fn llm_message(m: &LlmMessage) -> Value {
    let mut v = json!({
        "role": m.role,
        "content": m.content,
    });
    if !m.tool_calls.is_empty() {
        v["tool_calls"] =
            json!(m
            .tool_calls
            .iter()
            .map(|tc| json!({
                "function": {
                    "name": tc.function.as_ref().map(|f| f.name.clone()).unwrap_or_default(),
                    "arguments": tc.function.as_ref()
                        .and_then(|f| f.arguments.as_ref())
                        .and_then(|a| serde_json::from_str::<Value>(a).ok())
                        .unwrap_or(Value::Null),
                }
            }))
            .collect::<Vec<_>>());
    }
    if let Some(id) = &m.tool_call_id {
        v["tool_call_id"] = json!(id);
    }
    v
}

fn tool_spec(t: &ToolSpec) -> Value {
    json!({
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
        }
    })
}

/// Parses a non-streamed `/api/chat` response.
///
/// # Errors
/// `LlmError::Protocol` when the response has no `message` object.
pub fn parse_chat_response(json: &Value) -> Result<ChatResponse, LlmError> {
    let message = json
        .get("message")
        .ok_or_else(|| LlmError::Protocol("missing message".into()))?;
    let mut response = ChatResponse {
        content: message
            .get("content")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        thinking: None,
        tool_calls: parse_tool_calls(message),
        finish_reason: json
            .get("done_reason")
            .and_then(Value::as_str)
            .unwrap_or("stop")
            .to_string(),
    };
    // Ollama may return thinking in the message when a reasoning model
    // is used (model-dependent).
    if let Some(t) = message.get("thinking").and_then(Value::as_str) {
        response.thinking = Some(t.to_string());
    }
    Ok(response)
}

/// Parses one NDJSON line of a streaming response, mutating `response`
/// as chunks accumulate.
///
/// # Errors
/// `LlmError::Protocol` when the line is not valid JSON.
pub fn parse_stream_line(
    line: &str,
    response: &mut ChatResponse,
) -> Result<Option<StreamEvent>, LlmError> {
    if line.is_empty() {
        return Ok(None);
    }
    let v: Value = serde_json::from_str(line)
        .map_err(|e| LlmError::Protocol(format!("bad NDJSON: {e}: {line}")))?;
    if v.get("done").and_then(Value::as_bool).unwrap_or(false) {
        response.finish_reason = v
            .get("done_reason")
            .and_then(Value::as_str)
            .unwrap_or("stop")
            .to_string();
        response.tool_calls = v.get("message").map(parse_tool_calls).unwrap_or_default();
        return Ok(Some(StreamEvent::Done(response.clone())));
    }
    if let Some(content) = v.pointer("/message/content").and_then(Value::as_str)
        && !content.is_empty()
    {
        response.content.push_str(content);
        return Ok(Some(StreamEvent::Chunk {
            content: String::from(content),
            thinking: v
                .pointer("/message/thinking")
                .and_then(Value::as_str)
                .map(String::from),
        }));
    }
    if let Some(arr) = v.pointer("/message/tool_calls").and_then(Value::as_array)
        && let Some(call) = arr.first()
    {
        // Streaming tool calls arrive as a completed list in one
        // message; the first entry's delta is enough to wake the
        // assembler, the rest come through the `done` payload.
        let name = call.pointer("/function/name").and_then(Value::as_str);
        let args = call.pointer("/function/arguments").map(|a| {
            if a.is_string() {
                a.as_str().unwrap_or("").to_string()
            } else {
                a.to_string()
            }
        });
        return Ok(Some(StreamEvent::ToolCallDelta {
            index: 0,
            id: None,
            name: name.map(String::from),
            arguments: args,
        }));
    }
    Ok(None)
}

/// Extracts tool calls from a `message` object (never fails; missing or
/// malformed tool-call arrays yield an empty list).
fn parse_tool_calls(message: &Value) -> Vec<crate::agent::message::ToolCall> {
    let Some(calls) = message.get("tool_calls") else {
        return Vec::new();
    };
    let Some(arr) = calls.as_array() else {
        return Vec::new();
    };
    let mut out = Vec::new();
    for call in arr {
        let function = call.get("function");
        out.push(crate::agent::message::ToolCall {
            id: None,
            r#type: String::from("function"),
            function: Some(crate::agent::message::Function {
                name: function
                    .and_then(|f| f.get("name"))
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
                arguments: function.and_then(|f| f.get("arguments")).map(|a| {
                    if a.is_string() {
                        a.as_str().unwrap_or("").to_string()
                    } else {
                        a.to_string()
                    }
                }),
            }),
            result_content: None,
            result_error: None,
        });
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::agent::message::{Function, ToolCall};

    fn req() -> ChatRequest {
        ChatRequest {
            model: String::from("llama3.1"),
            messages: vec![LlmMessage {
                role: String::from("user"),
                content: String::from("hi"),
                tool_calls: Vec::new(),
                tool_call_id: None,
            }],
            tools: vec![ToolSpec {
                name: String::from("read_file"),
                description: String::from("read a file"),
                parameters: json!({"type": "object"}),
            }],
            ..Default::default()
        }
    }

    #[test]
    fn chat_body_has_expected_shape() {
        let body = build_chat_body(&req(), false);
        assert_eq!(body["model"], "llama3.1");
        assert_eq!(body["messages"][0]["role"], "user");
        assert_eq!(body["tools"][0]["function"]["name"], "read_file");
        assert_eq!(body["stream"], false);
        assert_eq!(body["options"]["num_ctx"], 4096);
    }

    #[test]
    fn response_with_tool_calls_parses() {
        let json = json!({
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "a.txt"}}}]
            },
            "done": true,
            "done_reason": "stop"
        });
        let r = parse_chat_response(&json).expect("parse");
        assert_eq!(r.tool_calls.len(), 1);
        let tc = &r.tool_calls[0];
        assert_eq!(
            tc.function.as_ref().map(|f| f.name.as_str()),
            Some("read_file")
        );
        assert_eq!(
            tc.function.as_ref().and_then(|f| f.arguments.as_deref()),
            Some(r#"{"path":"a.txt"}"#)
        );
    }

    #[test]
    fn stream_accumulates_chunks_then_done() {
        let mut response = ChatResponse::default();
        let ev = parse_stream_line(
            r#"{"message":{"role":"assistant","content":"hel"}}"#,
            &mut response,
        )
        .expect("line");
        assert!(matches!(ev, Some(StreamEvent::Chunk { .. })));
        let ev = parse_stream_line(
            r#"{"message":{"role":"assistant","content":"lo"}}"#,
            &mut response,
        )
        .expect("line");
        assert!(matches!(ev, Some(StreamEvent::Chunk { .. })));
        let ev = parse_stream_line(
            r#"{"message":{"role":"assistant","content":""},"done":true,"done_reason":"stop"}"#,
            &mut response,
        )
        .expect("line");
        assert!(matches!(ev, Some(StreamEvent::Done(_))));
        assert_eq!(response.content, "hello");
        assert_eq!(response.finish_reason, "stop");
    }

    #[test]
    fn stream_tool_calls_emit_deltas() {
        let mut response = ChatResponse::default();
        let ev = parse_stream_line(
            r#"{"message":{"tool_calls":[{"function":{"name":"read_file","arguments":{"path":"x"}}}]}}"#,
            &mut response,
        )
        .expect("line");
        match ev {
            Some(StreamEvent::ToolCallDelta { index, name, .. }) => {
                assert_eq!(index, 0);
                assert_eq!(name.as_deref(), Some("read_file"));
            }
            other => panic!("expected delta, got {other:?}"),
        }
    }

    #[test]
    fn tool_message_serializes_tool_call_id() {
        let m = LlmMessage {
            role: String::from("tool"),
            content: String::from("ok"),
            tool_calls: Vec::new(),
            tool_call_id: Some(String::from("call_1")),
        };
        let v = llm_message(&m);
        assert_eq!(v["tool_call_id"], "call_1");
    }

    #[test]
    fn tool_call_with_arguments_json_roundtrips() {
        let m = LlmMessage {
            role: String::from("assistant"),
            content: String::new(),
            tool_calls: vec![ToolCall {
                id: Some(String::from("c1")),
                r#type: String::from("function"),
                function: Some(Function {
                    name: String::from("read_file"),
                    arguments: Some(String::from(r#"{"path":"x"}"#)),
                }),
                result_content: None,
                result_error: None,
            }],
            tool_call_id: None,
        };
        let v = llm_message(&m);
        assert_eq!(v["tool_calls"][0]["function"]["arguments"]["path"], "x");
    }
}
