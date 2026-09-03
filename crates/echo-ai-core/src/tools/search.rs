//! Web search: the provider abstraction (`Brave` API, `Tavily` API,
//! `DuckDuckGo` HTML scrape) and the `web_search` tool.
//!
//! `DuckDuckGo` has no API key and scrapes its HTML endpoint; the other
//! two are JSON APIs. All three return the same `SearchResult` shape.
//!
//! Depends on: crate `llm::http`, `tools::tool`.

use futures_util::future::BoxFuture;
use serde_json::{Value, json};
use std::sync::Arc;

use crate::llm::http::HttpClient;

use super::tool::{Tool, ToolContext, ToolError, ToolOutput, arg_optional_u64, arg_string};

/// One search hit.
#[derive(Debug, Clone)]
pub struct SearchResult {
    /// Result title.
    pub title: String,
    /// Result URL.
    pub url: String,
    /// Snippet text.
    pub snippet: String,
}

/// A configured search backend.
#[derive(Debug, Clone)]
pub enum SearchProvider {
    /// Brave Search API.
    Brave {
        /// API key.
        api_key: String,
    },
    /// Tavily API.
    Tavily {
        /// API key.
        api_key: String,
    },
    /// `DuckDuckGo` HTML scraping.
    DuckDuckGo,
}

impl SearchProvider {
    /// Builds from config.
    #[must_use]
    pub fn from_config(cfg: &crate::config::Config) -> Option<Self> {
        match cfg.search.provider.as_str() {
            "brave" if !cfg.search.api_key.is_empty() => Some(Self::Brave {
                api_key: cfg.search.api_key.clone(),
            }),
            "tavily" if !cfg.search.api_key.is_empty() => Some(Self::Tavily {
                api_key: cfg.search.api_key.clone(),
            }),
            "duckduckgo" => Some(Self::DuckDuckGo),
            _ => None,
        }
    }

    /// Runs a search for `query`, returning up to `max` results.
    ///
    /// # Errors
    /// `ToolError::Execution` on transport or parse failures.
    pub async fn search(
        &self,
        http: &dyn HttpClient,
        query: &str,
        max: usize,
    ) -> Result<Vec<SearchResult>, ToolError> {
        match self {
            Self::Brave { api_key } => {
                let headers = [("X-Subscription-Token", api_key.as_str())];
                let url = format!(
                    "https://api.search.brave.com/res/v1/web/search?q={}&count={}",
                    urlencode(query),
                    max.min(20)
                );
                let json = http
                    .get_json(&url, &headers)
                    .await
                    .map_err(|e| ToolError::Execution(e.to_string()))?;
                Ok(parse_brave(&json, max))
            }
            Self::Tavily { api_key } => {
                let body = json!({
                    "api_key": api_key,
                    "query": query,
                    "max_results": max.min(10),
                });
                let json = http
                    .post_json("https://api.tavily.com/search", &[], body)
                    .await
                    .map_err(|e| ToolError::Execution(e.to_string()))?;
                Ok(parse_tavily(&json, max))
            }
            Self::DuckDuckGo => {
                let url = format!("https://html.duckduckgo.com/html/?q={}", urlencode(query));
                let resp = reqwest::Client::new()
                    .get(&url)
                    .header("User-Agent", "echo-ai/0.1")
                    .send()
                    .await
                    .map_err(|e| ToolError::Execution(format!("ddg: {e}")))?;
                let html = resp
                    .text()
                    .await
                    .map_err(|e| ToolError::Execution(format!("ddg read: {e}")))?;
                Ok(parse_ddg_html(&html, max))
            }
        }
    }
}

/// Parses `DuckDuckGo`'s HTML result page (result links + snippets).
fn parse_ddg_html(html: &str, max: usize) -> Vec<SearchResult> {
    let mut results = Vec::new();
    let mut rest = html;
    while results.len() < max {
        let Some(anchor_pos) = rest.find("class=\"result__a\"") else {
            break;
        };
        let anchor = &rest[anchor_pos..];
        // href="..." comes before the closing > of the anchor.
        let Some(href_start) = anchor.find("href=\"") else {
            break;
        };
        let href_start = href_start + 6;
        let href_end = anchor[href_start..]
            .find('"')
            .map_or(href_start, |p| href_start + p);
        let url = anchor[href_start..href_end].to_string();
        // Title text: after the > that closes the anchor tag.
        let Some(title_start) = anchor.find('>') else {
            break;
        };
        let title_end = anchor[title_start..]
            .find("</a>")
            .map_or(anchor.len(), |p| title_start + p);
        let title = strip_tags(&anchor[title_start + 1..title_end]);

        // Snippet: the next result__snippet block.
        let after_anchor = &anchor[title_end.min(anchor.len())..];
        let snippet = match after_anchor.find("class=\"result__snippet\"") {
            Some(sp) => {
                let s = &after_anchor[sp..];
                match s.find('>') {
                    Some(s_start) => {
                        let s_end = s[s_start..].find("</a>").map_or(s.len(), |p| s_start + p);
                        strip_tags(&s[s_start + 1..s_end])
                    }
                    None => String::new(),
                }
            }
            None => String::new(),
        };

        results.push(SearchResult {
            title,
            url,
            snippet,
        });
        rest = &rest[anchor_pos + 1..];
    }
    results
}

/// Removes HTML tags from a fragment (entity-safe-ish for snippets).
fn strip_tags(s: &str) -> String {
    let mut out = String::new();
    let mut in_tag = false;
    for c in s.chars() {
        match c {
            '<' => in_tag = true,
            '>' => in_tag = false,
            _ if !in_tag => out.push(c),
            _ => {}
        }
    }
    out.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Parses Brave's JSON response.
fn parse_brave(json: &Value, max: usize) -> Vec<SearchResult> {
    json.get("web")
        .and_then(|w| w.get("results"))
        .and_then(Value::as_array)
        .map(|arr| {
            arr.iter()
                .take(max)
                .filter_map(|r| {
                    let url = r.get("url").and_then(Value::as_str)?;
                    Some(SearchResult {
                        title: r
                            .get("title")
                            .and_then(Value::as_str)
                            .unwrap_or("")
                            .to_string(),
                        url: url.to_string(),
                        snippet: r
                            .get("description")
                            .and_then(Value::as_str)
                            .unwrap_or("")
                            .to_string(),
                    })
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Parses Tavily's JSON response.
fn parse_tavily(json: &Value, max: usize) -> Vec<SearchResult> {
    json.get("results")
        .and_then(Value::as_array)
        .map(|arr| {
            arr.iter()
                .take(max)
                .filter_map(|r| {
                    let url = r.get("url").and_then(Value::as_str)?;
                    Some(SearchResult {
                        title: r
                            .get("title")
                            .and_then(Value::as_str)
                            .unwrap_or("")
                            .to_string(),
                        url: url.to_string(),
                        snippet: r
                            .get("content")
                            .and_then(Value::as_str)
                            .unwrap_or("")
                            .to_string(),
                    })
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Minimal URL encoding for query strings.
fn urlencode(s: &str) -> String {
    let mut out = String::new();
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char);
            }
            _ => {
                use std::fmt::Write as _;
                let _ = write!(out, "%{b:02X}");
            }
        }
    }
    out
}

/// `web_search`: dispatches to the configured search provider.
pub struct WebSearch {
    provider: Arc<SearchProvider>,
}

impl WebSearch {
    /// Wraps a configured provider.
    #[must_use]
    pub fn new(provider: Arc<SearchProvider>) -> Self {
        Self { provider }
    }
}

impl Tool for WebSearch {
    fn name(&self) -> &'static str {
        "web_search"
    }

    fn description(&self) -> &'static str {
        "Search the web. Returns titles, URLs, and snippets."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 5}
            },
            "required": ["query"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        let provider = self.provider.clone();
        Box::pin(async move {
            if !ctx.safety.allow_network {
                return Err(ToolError::Safety(String::from("network access disabled")));
            }
            let query = arg_string(&args, "query")?;
            let max = arg_optional_u64(&args, "max_results")
                .and_then(|v| usize::try_from(v).ok())
                .unwrap_or(5);
            let results = provider
                .search(ctx.http.as_ref(), &query, max.max(1))
                .await?;
            if results.is_empty() {
                return Ok(ToolOutput::text(format!("no results for {query}")));
            }
            let mut text = String::new();
            for (i, r) in results.iter().enumerate() {
                use std::fmt::Write as _;
                let _ = writeln!(
                    text,
                    "{}. {} — {}\n   {}\n",
                    i + 1,
                    r.title,
                    r.url,
                    r.snippet
                );
            }
            Ok(ToolOutput::text(text))
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn brave_results_parse() {
        let json = json!({
            "web": {"results": [
                {"title": "T1", "url": "https://a.example", "description": "snippet one"},
                {"title": "T2", "url": "https://b.example", "description": "snippet two"}
            ]}
        });
        let results = parse_brave(&json, 5);
        assert_eq!(results.len(), 2);
        assert_eq!(results[0].title, "T1");
        assert_eq!(results[1].url, "https://b.example");
    }

    #[test]
    fn tavily_results_parse() {
        let json = json!({
            "results": [
                {"title": "T", "url": "https://c.example", "content": "snippet"}
            ]
        });
        let results = parse_tavily(&json, 5);
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].snippet, "snippet");
    }

    #[test]
    fn urlencoding_escapes_reserved_chars() {
        assert_eq!(urlencode("a b&c"), "a%20b%26c");
    }

    #[test]
    fn ddg_html_parses_results() {
        let html = r#"<div class="result">
            <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com">Example Title</a>
            <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com">A snippet <b>here</b>.</a>
        </div>"#;
        let results = parse_ddg_html(html, 5);
        assert_eq!(results.len(), 1);
        assert!(results[0].title.contains("Example Title"));
        assert!(results[0].snippet.contains("A snippet here"));
    }
}
