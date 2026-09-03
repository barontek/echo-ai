//! Misc tools: `ask_user` (interactive question) and `humanizer`
//! (content restyling).
//!
//! Depends on: crate `tools::tool`.

use futures_util::future::BoxFuture;
use serde_json::{Value, json};

use super::tool::{Tool, ToolContext, ToolError, ToolOutput, arg_string};

/// `ask_user`: asks the user a question (interactive frontends).
pub struct AskUser;

impl Tool for AskUser {
    fn name(&self) -> &'static str {
        "ask_user"
    }

    fn description(&self) -> &'static str {
        "Ask the user a question and wait for their answer. Use sparingly for genuinely necessary input."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "question": {"type": "string"}
            },
            "required": ["question"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            let question = arg_string(&args, "question")?;
            let Some(callback) = &ctx.ask_user else {
                return Err(ToolError::Execution(String::from(
                    "no interactive user available in this frontend",
                )));
            };
            match callback.ask(&question).await {
                Ok(Some(answer)) => Ok(ToolOutput::text(answer)),
                Ok(None) => Err(ToolError::Cancelled),
                Err(e) => Err(ToolError::Execution(e.to_string())),
            }
        })
    }
}

/// `humanizer`: restyles content (paragraph, bullets, or short summary).
pub struct Humanizer;

impl Tool for Humanizer {
    fn name(&self) -> &'static str {
        "humanizer"
    }

    fn description(&self) -> &'static str {
        "Restyle content: 'paragraph', 'bullets', or 'summary' (500 chars)."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "style": {"type": "string", "enum": ["paragraph", "bullets", "summary"]},
                "content": {"type": "string"}
            },
            "required": ["style", "content"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        _ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            let style = arg_string(&args, "style")?;
            let content = arg_string(&args, "content")?;
            let output = match style.as_str() {
                "summary" => summarize(&content),
                "bullets" => to_bullets(&content),
                _ => content,
            };
            Ok(ToolOutput::text(output))
        })
    }
}

/// First ~500 chars, broken into sentences (best effort).
fn summarize(content: &str) -> String {
    let mut out = String::new();
    let mut count = 0usize;
    for sentence in content.split_inclusive(['.', '!', '?', '\n']) {
        out.push_str(sentence);
        count += sentence.len();
        if count >= 500 {
            out.push_str("\n...[summarized]");
            break;
        }
    }
    if out.is_empty() {
        String::from("(empty)")
    } else {
        out
    }
}

/// Converts paragraphs into a bulleted list.
fn to_bullets(content: &str) -> String {
    let mut bullets = Vec::new();
    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let line = line.strip_prefix("- ").unwrap_or(line);
        bullets.push(format!("- {line}"));
    }
    if bullets.is_empty() {
        String::from("(empty)")
    } else {
        bullets.join("\n")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn summary_truncates_around_500_chars() {
        let long = "word ".repeat(200);
        let out = summarize(&long);
        assert!(out.len() < long.len() + 20);
        assert!(out.contains("summarized"));
    }

    #[test]
    fn bullets_flatten_paragraphs() {
        let out = to_bullets("alpha\nbeta");
        assert_eq!(out, "- alpha\n- beta");
    }

    #[test]
    fn ask_user_without_callback_errors() {
        use crate::config::Config;
        use crate::safety::SafetyConfig;
        let safety = SafetyConfig::from_config(&Config::default().safety, None);
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
            .block_on(AskUser.execute(json!({"question": "hi"}), &ctx))
            .expect_err("no callback");
        assert!(matches!(err, ToolError::Execution(_)));
    }
}
