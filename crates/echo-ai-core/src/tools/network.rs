//! Network tools: `web_fetch` (fetch + readable-text extraction) and
//! `rest_api` (generic HTTP with method selection).
//!
//! Both honor `allow_network`; neither runs when the safety policy
//! forbids it. Outputs are capped.
//!
//! Depends on: `reqwest` (via the shared HTTP client), crate `utils::html`,
//! `tools::tool`.

use futures_util::future::BoxFuture;
use serde_json::{Value, json};

use super::tool::{Tool, ToolContext, ToolError, ToolOutput, arg_optional_bool, arg_string};

/// `web_fetch`: fetches a URL and extracts readable text.
pub struct WebFetch;

impl Tool for WebFetch {
    fn name(&self) -> &'static str {
        "web_fetch"
    }

    fn description(&self) -> &'static str {
        "Fetch a URL and return its readable text content (boilerplate stripped, capped)."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "raw": {"type": "boolean", "description": "Return raw HTML instead of extracted text"}
            },
            "required": ["url"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            if !ctx.safety.allow_network {
                return Err(ToolError::Safety(String::from("network access disabled")));
            }
            let url = arg_string(&args, "url")?;
            let raw = arg_optional_bool(&args, "raw").unwrap_or(false);
            let max_chars = ctx.safety.web_fetch_max_chars;
            let body = fetch_text(ctx, &url).await?;
            if raw {
                return Ok(ToolOutput::text(
                    body.chars().take(max_chars).collect::<String>(),
                ));
            }
            let text = crate::utils::html::extract_text(&body, max_chars);
            Ok(ToolOutput::text(text))
        })
    }
}

/// `rest_api`: generic `GET`/`POST`/`PUT`/`DELETE`/`PATCH` against a
/// URL with a JSON body.
pub struct RestApi;

impl Tool for RestApi {
    fn name(&self) -> &'static str {
        "rest_api"
    }

    fn description(&self) -> &'static str {
        "Call a REST endpoint. Returns status and body (capped)."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"]},
                "url": {"type": "string"},
                "body": {"type": "object", "description": "JSON body for POST/PUT/PATCH"}
            },
            "required": ["method", "url"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            if !ctx.safety.allow_network {
                return Err(ToolError::Safety(String::from("network access disabled")));
            }
            let method = arg_string(&args, "method")?;
            let url = arg_string(&args, "url")?;
            let body = args.get("body").cloned().unwrap_or(Value::Null);
            let (status, text) = call_with_method(&method, &url, body)
                .await
                .map_err(ToolError::Execution)?;
            let capped: String = text.chars().take(8192).collect();
            Ok(ToolOutput::text(format!("HTTP {status}\n{capped}")))
        })
    }
}

/// Performs a `GET`/`POST`/`PUT`/`DELETE`/`PATCH` call with reqwest,
/// returning `(status, body_text)`.
async fn call_with_method(
    method: &str,
    url: &str,
    body: Value,
) -> std::result::Result<(u16, String), String> {
    let client = reqwest::Client::new();
    let builder = match method {
        "GET" => client.get(url),
        "POST" => client.post(url).json(&body),
        "PUT" => client.put(url).json(&body),
        "DELETE" => client.delete(url),
        "PATCH" => client.patch(url).json(&body),
        other => return Err(format!("unsupported method {other}")),
    };
    let resp = builder.send().await.map_err(|e| e.to_string())?;
    let status = resp.status().as_u16();
    let text = resp.text().await.map_err(|e| e.to_string())?;
    Ok((status, text))
}

/// Shared `GET`-style fetch returning the raw body (capped by the
/// caller). Used by `web_fetch`.
pub(crate) async fn fetch_text(_ctx: &ToolContext<'_>, url: &str) -> Result<String, ToolError> {
    let resp = reqwest::Client::new()
        .get(url)
        .header("User-Agent", "echo-ai/0.1")
        .send()
        .await
        .map_err(|e| ToolError::Execution(format!("fetch {url}: {e}")))?;
    let status = resp.status().as_u16();
    if status != 200 {
        return Err(ToolError::Execution(format!("fetch {url}: HTTP {status}")));
    }
    let bytes = resp
        .bytes()
        .await
        .map_err(|e| ToolError::Execution(format!("read {url}: {e}")))?;
    // Cap the raw body before decoding (defense against huge pages).
    let bytes = bytes.into_iter().take(2 * 1024 * 1024).collect::<Vec<_>>();
    Ok(String::from_utf8_lossy(&bytes).into_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn network_disabled_is_safety_error() {
        use crate::config::Config;
        use crate::safety::SafetyConfig;
        let mut toml = Config::default().safety;
        toml.allow_network = false;
        let safety = SafetyConfig::from_config(&toml, None);
        let config = Config::default();
        let ctx = ToolContext {
            safety: &safety,
            config: &config,
            session: None,
            change_tracker: None,
            ask_user: None,
            http: std::sync::Arc::new(crate::llm::http::ReqwestClient::new()),
        };
        let err = tokio::runtime::Runtime::new()
            .expect("rt")
            .block_on(WebFetch.execute(json!({"url": "https://example.com"}), &ctx))
            .expect_err("network disabled");
        assert!(matches!(err, ToolError::Safety(_)));
    }
}
