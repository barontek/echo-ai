//! `deep_search`: multi-step research — web search, fetch the top
//! pages, and combine the findings into a single result.
//!
//! the original implementation's double-free bug (ownership transferred before
//! validation) is structurally impossible here: the search results are
//! owned values, and fetch failures are recorded per-URL, never
//! fatal to the whole run.
//!
//! Depends on: crate `tools::{network, search, tool}`.

use futures_util::future::BoxFuture;
use serde_json::{Value, json};
use std::sync::Arc;

use super::network::fetch_text;
use super::search::SearchProvider;
use super::tool::{Tool, ToolContext, ToolError, ToolOutput, arg_optional_u64, arg_string};

/// `deep_search`: research a topic by searching then reading top pages.
pub struct DeepSearch {
    search: Arc<SearchProvider>,
}

impl DeepSearch {
    /// Wraps the configured search provider.
    #[must_use]
    pub fn new(search: Arc<SearchProvider>) -> Self {
        Self { search }
    }
}

impl Tool for DeepSearch {
    fn name(&self) -> &'static str {
        "deep_search"
    }

    fn description(&self) -> &'static str {
        "Research a topic: search the web, fetch the top pages, and return combined findings."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_pages": {"type": "integer", "default": 3}
            },
            "required": ["query"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        let search = self.search.clone();
        Box::pin(async move {
            if !ctx.safety.allow_network {
                return Err(ToolError::Safety(String::from("network access disabled")));
            }
            let query = arg_string(&args, "query")?;
            let max_pages = arg_optional_u64(&args, "max_pages")
                .and_then(|v| usize::try_from(v).ok())
                .unwrap_or(3);
            let results = search
                .search(ctx.http.as_ref(), &query, max_pages.max(1))
                .await?;
            let mut findings = Vec::new();
            let mut failures = Vec::new();
            for (i, r) in results.iter().take(max_pages).enumerate() {
                let body = match fetch_text(ctx, &r.url).await {
                    Ok(b) => b,
                    Err(e) => {
                        failures.push(format!("{}: {e}", r.url));
                        continue;
                    }
                };
                let text = crate::utils::html::extract_text(&body, 4000);
                findings.push(json!({
                    "index": i + 1,
                    "title": r.title,
                    "url": r.url,
                    "text": text,
                }));
            }
            let mut output = serde_json::Map::new();
            output.insert(String::from("query"), json!(query));
            output.insert(String::from("findings"), Value::Array(findings));
            if !failures.is_empty() {
                output.insert(String::from("fetch_failures"), json!(failures));
            }
            let value = Value::Object(output);
            let text = format!(
                "Deep search on \"{query}\": {} pages read, {} failed.\n{}",
                value
                    .get("findings")
                    .and_then(Value::as_array)
                    .map_or(0, Vec::len),
                failures.len(),
                serde_json::to_string_pretty(&value).unwrap_or_else(|_| String::from("{}"))
            );
            Ok(ToolOutput::structured(text, value))
        })
    }
}
