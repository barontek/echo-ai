//! HTTP plumbing for the provider layer: a mockable `HttpClient` trait
//! and the reqwest-backed implementation, plus the line-oriented stream
//! abstraction every provider parser consumes.
//!
//! Providers never touch `reqwest` directly — tests inject a mock
//! client that returns fixture bodies (the Rust analogue of the C
//! project's `curl_stub`).
//!
//! Depends on: `reqwest`, `serde_json`, `tokio`, crate `llm::provider`.

use futures_util::StreamExt;
use futures_util::future::BoxFuture;
use serde_json::Value;
use tokio::sync::mpsc;

use super::provider::LlmError;

/// A stream of HTTP response lines (`Ok(line)` per line, then close).
pub type LineStream = mpsc::Receiver<Result<String, LlmError>>;

/// Minimal outbound HTTP surface used by providers (boxed futures keep
/// the trait dyn-compatible for the mock-injection pattern).
pub trait HttpClient: Send + Sync {
    /// `POST`s a JSON body and returns the parsed JSON response.
    ///
    /// # Errors
    /// `LlmError::Transport` on connect/read failures, `LlmError::Http`
    /// on non-success status.
    fn post_json(
        &self,
        url: &str,
        headers: &[(&str, &str)],
        body: Value,
    ) -> BoxFuture<'_, Result<Value, LlmError>>;

    /// `GET`s a URL and returns the parsed JSON response.
    ///
    /// # Errors
    /// Same as [`Self::post_json`].
    fn get_json(
        &self,
        url: &str,
        headers: &[(&str, &str)],
    ) -> BoxFuture<'_, Result<Value, LlmError>>;

    /// `POST`s a JSON body and returns a line stream of the response.
    ///
    /// # Errors
    /// Fails only before the response headers arrive.
    fn post_stream(
        &self,
        url: &str,
        headers: &[(&str, &str)],
        body: Value,
    ) -> BoxFuture<'_, Result<LineStream, LlmError>>;
}

/// reqwest-backed implementation (rustls; no system TLS deps).
#[derive(Debug, Clone, Default)]
pub struct ReqwestClient {
    client: reqwest::Client,
}

impl ReqwestClient {
    /// Creates a client with a 60s timeout and rustls TLS.
    ///
    /// # Panics
    /// Cannot panic in practice: the builder only fails on invalid
    /// configuration, and the defaults are always valid.
    #[allow(clippy::expect_used)] // invariant: default config cannot fail
    #[must_use]
    pub fn new() -> Self {
        Self {
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(60))
                .build()
                .expect("reqwest client build cannot fail with defaults"),
        }
    }
}

impl HttpClient for ReqwestClient {
    fn post_json(
        &self,
        url: &str,
        headers: &[(&str, &str)],
        body: Value,
    ) -> BoxFuture<'_, Result<Value, LlmError>> {
        let url = String::from(url);
        let headers: Vec<(String, String)> = headers
            .iter()
            .map(|(k, v)| ((*k).to_string(), (*v).to_string()))
            .collect();
        Box::pin(async move {
            let mut builder = self.client.post(&url).json(&body);
            for (k, v) in &headers {
                builder = builder.header(k.as_str(), v.as_str());
            }
            let resp = builder
                .send()
                .await
                .map_err(|e| LlmError::Transport(e.to_string()))?;
            let status = resp.status().as_u16();
            let text = resp
                .text()
                .await
                .map_err(|e| LlmError::Transport(e.to_string()))?;
            if status != 200 {
                return Err(LlmError::Http {
                    status,
                    body: text.chars().take(500).collect(),
                });
            }
            serde_json::from_str(&text).map_err(|e| LlmError::Protocol(format!("{e}: {text}")))
        })
    }

    fn get_json(
        &self,
        url: &str,
        headers: &[(&str, &str)],
    ) -> BoxFuture<'_, Result<Value, LlmError>> {
        let url = String::from(url);
        let headers: Vec<(String, String)> = headers
            .iter()
            .map(|(k, v)| ((*k).to_string(), (*v).to_string()))
            .collect();
        Box::pin(async move {
            let mut builder = self.client.get(&url);
            for (k, v) in &headers {
                builder = builder.header(k.as_str(), v.as_str());
            }
            let resp = builder
                .send()
                .await
                .map_err(|e| LlmError::Transport(e.to_string()))?;
            let status = resp.status().as_u16();
            let text = resp
                .text()
                .await
                .map_err(|e| LlmError::Transport(e.to_string()))?;
            if status != 200 {
                return Err(LlmError::Http {
                    status,
                    body: text.chars().take(500).collect(),
                });
            }
            serde_json::from_str(&text).map_err(|e| LlmError::Protocol(format!("{e}: {text}")))
        })
    }

    fn post_stream(
        &self,
        url: &str,
        headers: &[(&str, &str)],
        body: Value,
    ) -> BoxFuture<'_, Result<LineStream, LlmError>> {
        let url = String::from(url);
        let headers: Vec<(String, String)> = headers
            .iter()
            .map(|(k, v)| ((*k).to_string(), (*v).to_string()))
            .collect();
        Box::pin(async move {
            let mut builder = self.client.post(&url).json(&body);
            for (k, v) in &headers {
                builder = builder.header(k.as_str(), v.as_str());
            }
            let resp = builder
                .send()
                .await
                .map_err(|e| LlmError::Transport(e.to_string()))?;
            let status = resp.status().as_u16();
            if status != 200 {
                let text = resp
                    .text()
                    .await
                    .map_err(|e| LlmError::Transport(e.to_string()))?;
                return Err(LlmError::Http {
                    status,
                    body: text.chars().take(500).collect(),
                });
            }
            let (tx, rx) = mpsc::channel(64);
            tokio::spawn(async move {
                let mut bytes = resp.bytes_stream();
                let mut buf = Vec::new();
                while let Some(chunk) = bytes.next().await {
                    match chunk {
                        Ok(c) => buf.extend_from_slice(&c),
                        Err(e) => {
                            let _ = tx.send(Err(LlmError::Transport(e.to_string()))).await;
                            return;
                        }
                    }
                    while let Some(pos) = buf.iter().position(|b| *b == b'\n') {
                        let line: Vec<u8> = buf.drain(..=pos).collect();
                        let line = String::from_utf8_lossy(&line);
                        let line = line.trim_end_matches('\n').trim_end_matches('\r');
                        if tx.send(Ok(String::from(line))).await.is_err() {
                            return; // receiver dropped: cancel
                        }
                    }
                }
            });
            Ok(rx)
        })
    }
}

/// Builds a bounded stream of lines for tests (synchronous feed into an
/// unbounded channel).
#[must_use]
pub fn lines_to_stream(lines: Vec<String>) -> LineStream {
    let (tx, rx) = mpsc::channel(64);
    for line in lines {
        let _ = tx.try_send(Ok(line));
    }
    drop(tx);
    rx
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn line_stream_delivers_all_lines_then_closes() {
        let mut rx = lines_to_stream(vec![String::from("a"), String::from("b"), String::new()]);
        let rt = tokio::runtime::Runtime::new().expect("rt");
        rt.block_on(async {
            let mut got = Vec::new();
            while let Some(line) = rx.recv().await {
                got.push(line.expect("ok"));
            }
            assert_eq!(got, vec!["a", "b", ""]);
        });
    }

    #[test]
    fn reqwest_client_constructs() {
        let _ = ReqwestClient::new();
    }
}
