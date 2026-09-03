//! `git` tool: common repository operations in a subprocess with a hard
//! timeout (status, diff, log, add, commit, push, pull, branch, stash).
//!
//! Depends on: `tokio`, crate `tools::{process, tool}`.

use futures_util::future::BoxFuture;
use serde_json::{Value, json};
use std::time::Duration;

use super::process::run_command;
use super::tool::{Tool, ToolContext, ToolError, ToolOutput, arg_optional_string, arg_string};

/// `git`: runs `git <operation>` against the workspace repository.
pub struct Git;

impl Tool for Git {
    fn name(&self) -> &'static str {
        "git"
    }

    fn description(&self) -> &'static str {
        "Run a git operation (status, diff, log, add, commit, push, pull, branch, stash, show, checkout) in the workspace."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["status", "diff", "log", "add", "commit", "push", "pull", "branch", "stash", "show", "checkout"]},
                "args": {"type": "array", "items": {"type": "string"}, "description": "Extra arguments, e.g. [\"-m\", \"message\"] for commit"}
            },
            "required": ["operation"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            let operation = arg_string(&args, "operation")?;
            let extra: Vec<String> = args
                .get("args")
                .and_then(Value::as_array)
                .map(|a| {
                    a.iter()
                        .filter_map(Value::as_str)
                        .map(String::from)
                        .collect()
                })
                .unwrap_or_default();
            let extra_refs: Vec<&str> = extra.iter().map(String::as_str).collect();
            let mut all: Vec<&str> = vec![&operation];
            all.extend(extra_refs);
            let out = run_command(
                "git",
                &all,
                Duration::from_secs(120),
                Some(&ctx.safety.workspace),
            )
            .await?;
            if out.status != 0 && !out.stderr.is_empty() {
                return Ok(ToolOutput::text(format!(
                    "[git {operation} exited {status}]\n{stderr}",
                    status = out.status,
                    stderr = out.stderr
                )));
            }
            let _ = arg_optional_string(&args, "args");
            Ok(ToolOutput::text(out.stdout))
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::Config;
    use crate::safety::SafetyConfig;
    use std::sync::atomic::{AtomicUsize, Ordering};

    static COUNTER: AtomicUsize = AtomicUsize::new(0);

    #[test]
    fn git_status_runs_in_workspace() {
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir().join(format!("echo-git-{}-{n}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("dir");
        // Not a git repo: expect a clean error report, not a crash.
        let safety = SafetyConfig::from_config(&Config::default().safety, Some(dir.clone()));
        let config = Config::default();
        let ctx = ToolContext {
            safety: &safety,
            config: &config,
            session: None,
            change_tracker: None,
            ask_user: None,
            http: std::sync::Arc::new(crate::llm::http::ReqwestClient::new()),
        };
        let out = tokio::runtime::Runtime::new()
            .expect("rt")
            .block_on(Git.execute(json!({"operation": "status"}), &ctx))
            .expect("tool");
        assert!(!out.text.is_empty());
        let _ = std::fs::remove_dir_all(&dir);
    }
}
