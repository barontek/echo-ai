//! `OpenAI`-compatible provider: `/v1/chat/completions` with `SSE`
//! streaming. Covers `LM Studio`, `vLLM`, llama.cpp, and — via thin
//! subclasses — `OpenCode Zen` and `OpenCode Go`.
//!
//! Parser is a pure function over SSE lines; tests feed fixture lines
//! (the C version's `openai_compatible_stream` ported in spirit).
//!
//! Depends on: `serde_json`, `tokio`, crate `llm::{http,provider}`.

use futures_util::future::BoxFuture;
use serde_json::{Value, json};

use super::http::HttpClient;
use super::provider::{
    ChatRequest, ChatResponse, LlmError, LlmMessage, LlmProvider, StreamEvent, ToolSpec,
};

/// OpenAI-compatible provider.
#[derive(Clone)]
pub struct OpenAiCompatible {
    base_url: String,
    /// Optional `Authorization: Bearer` token.
    token: Option<String>,
    http: std::sync::Arc<dyn HttpClient>,
}

impl OpenAiCompatible {
    /// Creates a provider against `base_url`. `token` is attached as a
    /// Bearer header when present.
    pub fn new(
        base_url: String,
        token: Option<String>,
        http: std::sync::Arc<dyn HttpClient>,
    ) -> Self {
        Self {
            base_url,
            token,
            http,
        }
    }

    fn headers(&self) -> Vec<(&'static str, String)> {
        self.token
            .as_ref()
            .map(|t| vec![("Authorization", format!("Bearer {t}"))])
            .unwrap_or_default()
    }

    fn endpoint(&self) -> String {
        let base = self.base_url.trim_end_matches('/');
        // Accept both "http://host:port" and "http://host:port/v1".
        if base.ends_with("/v1") {
            format!("{base}/chat/completions")
        } else {
            format!("{base}/v1/chat/completions")
        }
    }
}

impl LlmProvider for OpenAiCompatible {
    fn name(&self) -> &'static str {
        "openai_compatible"
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

impl OpenAiCompatible {
    async fn chat_impl(&self, req: &ChatRequest) -> Result<ChatResponse, LlmError> {
        let owned = self.headers();
        let headers: Vec<(&str, &str)> = owned.iter().map(|(k, v)| (*k, v.as_str())).collect();
        let body = build_chat_body(req, false);
        let json = self
            .http
            .post_json(&self.endpoint(), &headers, body)
            .await?;
        parse_chat_response(&json)
    }

    async fn chat_stream_impl(
        &self,
        req: &ChatRequest,
    ) -> Result<tokio::sync::mpsc::Receiver<StreamEvent>, LlmError> {
        let owned = self.headers();
        let headers: Vec<(&str, &str)> = owned.iter().map(|(k, v)| (*k, v.as_str())).collect();
        let body = build_chat_body(req, true);
        let mut lines = self
            .http
            .post_stream(&self.endpoint(), &headers, body)
            .await?;
        let (tx, rx) = tokio::sync::mpsc::channel(64);
        tokio::spawn(async move {
            let mut response = ChatResponse::default();
            let mut calls: Vec<Option<(Option<String>, String, String)>> = Vec::new();
            while let Some(line) = lines.recv().await {
                match line {
                    Ok(l) => match parse_sse_line(&l, &mut response, &mut calls) {
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

/// Builds the `/v1/chat/completions` request body.
pub fn build_chat_body(req: &ChatRequest, stream: bool) -> Value {
    let mut body = json!({
        "model": req.model,
        "messages": req.messages.iter().map(llm_message).collect::<Vec<_>>(),
        "tools": req.tools.iter().map(tool_spec).collect::<Vec<_>>(),
        "temperature": req.temperature,
        "stream": stream,
    });
    if let Some(effort) = &req.effort
        && !effort.is_empty()
        && effort != "none"
    {
        body["reasoning_effort"] = json!(effort);
    }
    body
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
                "id": tc.id.clone().unwrap_or_default(),
                "type": "function",
                "function": {
                    "name": tc.function.as_ref().map(|f| f.name.clone()).unwrap_or_default(),
                    "arguments": tc.function.as_ref()
                        .and_then(|f| f.arguments.as_ref())
                        .cloned()
                        .unwrap_or_else(|| String::from("{}")),
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

/// Parses a non-streamed response.
///
/// # Errors
/// `LlmError::Protocol` when the response has no `choices[0].message`.
pub fn parse_chat_response(json: &Value) -> Result<ChatResponse, LlmError> {
    let choice = json
        .pointer("/choices/0")
        .ok_or_else(|| LlmError::Protocol("missing choices[0]".into()))?;
    let message = choice
        .get("message")
        .ok_or_else(|| LlmError::Protocol("missing message".into()))?;
    Ok(ChatResponse {
        content: message
            .get("content")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        thinking: message
            .get("reasoning_content")
            .and_then(Value::as_str)
            .map(String::from),
        tool_calls: parse_tool_calls(message),
        finish_reason: choice
            .get("finish_reason")
            .and_then(Value::as_str)
            .unwrap_or("stop")
            .to_string(),
    })
}

/// State for streaming tool-call assembly across SSE lines.
pub type DeltaAccum = Vec<Option<(Option<String>, String, String)>>;

/// Parses one `SSE` line (`data: {...}` or `data: [DONE]`).
///
/// `calls` accumulates tool-call deltas across lines; `response`
/// accumulates content.
///
/// # Errors
/// `LlmError::Protocol` when the line is not valid `SSE`/`JSON`.
pub fn parse_sse_line(
    line: &str,
    response: &mut ChatResponse,
    calls: &mut DeltaAccum,
) -> Result<Option<StreamEvent>, LlmError> {
    let line = line.trim();
    if line.is_empty() {
        return Ok(None);
    }
    if let Some(payload) = line.strip_prefix("data:") {
        let payload = payload.trim();
        if payload == "[DONE]" {
            response.finish_reason = String::from("stop");
            response.tool_calls = assemble_calls(calls);
            return Ok(Some(StreamEvent::Done(response.clone())));
        }
        let v: Value = serde_json::from_str(payload)
            .map_err(|e| LlmError::Protocol(format!("bad SSE: {e}: {line}")))?;
        let choice = v
            .pointer("/choices/0")
            .ok_or_else(|| LlmError::Protocol("missing choices[0]".into()))?;
        let delta = choice.get("delta").cloned().unwrap_or(Value::Null);
        let mut event: Option<StreamEvent> = None;
        if let Some(content) = delta.get("content").and_then(Value::as_str) {
            if !content.is_empty() {
                response.content.push_str(content);
                event = Some(StreamEvent::Chunk {
                    content: String::from(content),
                    thinking: delta
                        .get("reasoning_content")
                        .and_then(Value::as_str)
                        .map(String::from),
                });
            }
        } else if let Some(thinking) = delta.get("reasoning_content").and_then(Value::as_str)
            && !thinking.is_empty()
        {
            response
                .thinking
                .get_or_insert_with(String::new)
                .push_str(thinking);
            event = Some(StreamEvent::Chunk {
                content: String::new(),
                thinking: Some(String::from(thinking)),
            });
        }
        if let Some(deltas) = delta.get("tool_calls").and_then(Value::as_array) {
            for d in deltas {
                let index = d
                    .get("index")
                    .and_then(Value::as_u64)
                    .and_then(|i| usize::try_from(i).ok())
                    .unwrap_or(0);
                let id = d.get("id").and_then(Value::as_str).map(String::from);
                let name = d
                    .pointer("/function/name")
                    .and_then(Value::as_str)
                    .map(String::from);
                let arguments = d
                    .pointer("/function/arguments")
                    .and_then(Value::as_str)
                    .map(String::from);
                while calls.len() <= index {
                    calls.push(None);
                }
                let entry =
                    calls[index].get_or_insert_with(|| (None, String::new(), String::new()));
                if entry.0.is_none() {
                    entry.0 = id;
                }
                if let Some(n) = name {
                    entry.1.push_str(&n);
                }
                if let Some(a) = arguments {
                    entry.2.push_str(&a);
                }
                event = Some(StreamEvent::ToolCallDelta {
                    index,
                    id: None,
                    name: None,
                    arguments: None,
                });
            }
        }
        if let Some(reason) = choice.get("finish_reason").and_then(Value::as_str) {
            response.finish_reason = String::from(reason);
            response.tool_calls = assemble_calls(calls);
            return Ok(Some(StreamEvent::Done(response.clone())));
        }
        return Ok(event);
    }
    // Some providers emit bare JSON lines without the `data:` prefix.
    let v: Value = serde_json::from_str(line)
        .map_err(|e| LlmError::Protocol(format!("bad SSE line: {e}: {line}")))?;
    if let Some(choice) = v.pointer("/choices/0")
        && let Some(reason) = choice.get("finish_reason").and_then(Value::as_str)
    {
        response.finish_reason = String::from(reason);
        return Ok(Some(StreamEvent::Done(response.clone())));
    }
    Ok(None)
}

/// Assembles accumulated tool-call deltas into `ToolCall`s.
fn assemble_calls(calls: &DeltaAccum) -> Vec<crate::agent::message::ToolCall> {
    calls
        .iter()
        .filter_map(|c| c.as_ref())
        .map(|(id, name, arguments)| crate::agent::message::ToolCall {
            id: id.clone(),
            r#type: String::from("function"),
            function: Some(crate::agent::message::Function {
                name: name.clone(),
                arguments: Some(arguments.clone()),
            }),
            result_content: None,
            result_error: None,
        })
        .collect()
}

/// Extracts tool calls from a non-streamed `message` object (never
/// fails; missing or malformed arrays yield an empty list).
fn parse_tool_calls(message: &Value) -> Vec<crate::agent::message::ToolCall> {
    let Some(calls) = message.get("tool_calls") else {
        return Vec::new();
    };
    let Some(arr) = calls.as_array() else {
        return Vec::new();
    };
    let mut out = Vec::new();
    for call in arr {
        out.push(crate::agent::message::ToolCall {
            id: call.get("id").and_then(Value::as_str).map(String::from),
            r#type: call
                .get("type")
                .and_then(Value::as_str)
                .unwrap_or("function")
                .to_string(),
            function: Some(crate::agent::message::Function {
                name: call
                    .pointer("/function/name")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
                arguments: call
                    .pointer("/function/arguments")
                    .and_then(Value::as_str)
                    .map(String::from),
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

    fn req() -> ChatRequest {
        ChatRequest {
            model: String::from("qwen3-coder"),
            messages: vec![LlmMessage {
                role: String::from("user"),
                content: String::from("hi"),
                tool_calls: Vec::new(),
                tool_call_id: None,
            }],
            tools: vec![ToolSpec {
                name: String::from("bash"),
                description: String::from("run a command"),
                parameters: json!({"type": "object"}),
            }],
            ..Default::default()
        }
    }

    #[test]
    fn body_shape_and_endpoint() {
        let body = build_chat_body(&req(), true);
        assert_eq!(body["model"], "qwen3-coder");
        assert_eq!(body["stream"], true);
        assert_eq!(body["tools"][0]["function"]["name"], "bash");
        let p = OpenAiCompatible::new(
            String::from("http://localhost:1234"),
            None,
            std::sync::Arc::new(super::super::http::ReqwestClient::new()),
        );
        assert_eq!(p.endpoint(), "http://localhost:1234/v1/chat/completions");
        let p2 = OpenAiCompatible::new(
            String::from("http://localhost:1234/v1"),
            None,
            std::sync::Arc::new(super::super::http::ReqwestClient::new()),
        );
        assert_eq!(p2.endpoint(), "http://localhost:1234/v1/chat/completions");
    }

    #[test]
    fn non_stream_response_parses() {
        let json = json!({
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "hi there",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "bash", "arguments": "{\"cmd\":\"ls\"}"}
                    }]
                },
                "finish_reason": "tool_calls"
            }]
        });
        let r = parse_chat_response(&json).expect("parse");
        assert_eq!(r.content, "hi there");
        assert_eq!(r.finish_reason, "tool_calls");
        assert_eq!(r.tool_calls[0].id.as_deref(), Some("call_1"));
        assert_eq!(
            r.tool_calls[0]
                .function
                .as_ref()
                .and_then(|f| f.arguments.as_deref()),
            Some(r#"{"cmd":"ls"}"#)
        );
    }

    #[test]
    fn reasoning_content_maps_to_thinking() {
        let json = json!({
            "choices": [{
                "message": {"role": "assistant", "content": "answer", "reasoning_content": "think"},
                "finish_reason": "stop"
            }]
        });
        let r = parse_chat_response(&json).expect("parse");
        assert_eq!(r.thinking.as_deref(), Some("think"));
    }

    #[test]
    fn sse_stream_assembles_tool_call_deltas() {
        let mut response = ChatResponse::default();
        let mut calls: DeltaAccum = Vec::new();
        let l1 = parse_sse_line(
            r#"data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"read_","arguments":"{\"path\":"}}]}}]}"#,
            &mut response,
            &mut calls,
        )
        .expect("l1");
        assert!(matches!(l1, Some(StreamEvent::ToolCallDelta { .. })));
        let l2 = parse_sse_line(
            r#"data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"file","arguments":"\"a.txt\"}"}}]}}]}"#,
            &mut response,
            &mut calls,
        )
        .expect("l2");
        assert!(matches!(l2, Some(StreamEvent::ToolCallDelta { .. })));
        let l3 = parse_sse_line(
            r#"data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}"#,
            &mut response,
            &mut calls,
        )
        .expect("l3");
        match l3 {
            Some(StreamEvent::Done(done)) => {
                assert_eq!(done.tool_calls.len(), 1);
                let tc = &done.tool_calls[0];
                assert_eq!(tc.id.as_deref(), Some("call_1"));
                assert_eq!(
                    tc.function.as_ref().map(|f| f.name.as_str()),
                    Some("read_file")
                );
                assert_eq!(
                    tc.function.as_ref().and_then(|f| f.arguments.as_deref()),
                    Some(r#"{"path":"a.txt"}"#)
                );
            }
            other => panic!("expected Done, got {other:?}"),
        }
    }

    #[test]
    fn sse_done_marker_finishes_stream() {
        let mut response = ChatResponse::default();
        let mut calls: DeltaAccum = Vec::new();
        let ev = parse_sse_line("data: [DONE]", &mut response, &mut calls).expect("line");
        assert!(matches!(ev, Some(StreamEvent::Done(_))));
    }

    #[test]
    fn content_chunks_accumulate() {
        let mut response = ChatResponse::default();
        let mut calls: DeltaAccum = Vec::new();
        parse_sse_line(
            r#"data: {"choices":[{"delta":{"content":"hel"}}]}"#,
            &mut response,
            &mut calls,
        )
        .expect("l1");
        parse_sse_line(
            r#"data: {"choices":[{"delta":{"content":"lo"}}]}"#,
            &mut response,
            &mut calls,
        )
        .expect("l2");
        assert_eq!(response.content, "hello");
    }
}
