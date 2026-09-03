//! Shell-execution tools: `bash` and `python_execute`, built on the
//! process-group runner with a hard timeout.
//!
//! The destructive-command screen is a best-effort warning layer (the
//! real boundary is approval gating by the agent loop); both tools
//! report the same contract: stdout, stderr, status.
//!
//! Depends on: `tokio`, crate `tools::{process, tool}`.

use futures_util::future::BoxFuture;
use serde_json::{Value, json};
use std::time::Duration;

use super::process::run_command;
use super::tool::{Tool, ToolContext, ToolError, ToolOutput, arg_string};

fn timeout_for(ctx: &ToolContext<'_>) -> Duration {
    ctx.safety.max_execution_time
}

/// `bash`: runs a shell command with a hard timeout.
pub struct Bash;

impl Tool for Bash {
    fn name(&self) -> &'static str {
        "bash"
    }

    fn description(&self) -> &'static str {
        "Run a bash command. Output is capped; the process group is killed on timeout."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run"}
            },
            "required": ["command"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            let command = arg_string(&args, "command")?;
            let timeout = timeout_for(ctx);
            let out = run_command(
                "bash",
                &["-lc", &command],
                timeout,
                Some(&ctx.safety.workspace),
            )
            .await?;
            Ok(render(&out.stdout, &out.stderr, out.status))
        })
    }
}

/// `python_execute`: runs Python 3 code with a hard timeout.
pub struct PythonExecute;

impl Tool for PythonExecute {
    fn name(&self) -> &'static str {
        "python_execute"
    }

    fn description(&self) -> &'static str {
        "Execute Python 3 code in a subprocess. Output is capped; the process group is killed on timeout."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python 3 source to run"}
            },
            "required": ["code"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            let code = arg_string(&args, "code")?;
            let timeout = timeout_for(ctx);
            let out = run_command(
                "python3",
                &["-c", &code],
                timeout,
                Some(&ctx.safety.workspace),
            )
            .await?;
            Ok(render(&out.stdout, &out.stderr, out.status))
        })
    }
}

fn render(stdout: &str, stderr: &str, status: i32) -> ToolOutput {
    use std::fmt::Write as _;
    let mut text = String::new();
    if !stdout.is_empty() {
        text.push_str(stdout);
    }
    if !stderr.is_empty() {
        if !text.is_empty() {
            text.push('\n');
        }
        let _ = writeln!(text, "[stderr]\n{stderr}");
    }
    if status == 0 {
        if text.is_empty() {
            text.push_str("(no output)");
        }
    } else {
        let _ = writeln!(text, "\n[exit status {status}]");
    }
    ToolOutput::text(text)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::Config;
    use crate::safety::SafetyConfig;
    use std::sync::atomic::{AtomicUsize, Ordering};

    static COUNTER: AtomicUsize = AtomicUsize::new(0);

    fn setup() -> (SafetyConfig, std::path::PathBuf) {
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir().join(format!("echo-shell-{}-{n}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("dir");
        let safety = SafetyConfig::from_config(&Config::default().safety, Some(dir.clone()));
        (safety, dir)
    }

    fn run<T: Tool>(tool: &T, args: Value) -> ToolOutput {
        let (safety, _dir) = setup();
        let config = Config::default();
        let ctx = ToolContext {
            safety: &safety,
            config: &config,
            session: None,
            change_tracker: None,
            ask_user: None,
            http: std::sync::Arc::new(crate::llm::http::ReqwestClient::new()),
        };
        tokio::runtime::Runtime::new()
            .expect("rt")
            .block_on(tool.execute(args, &ctx))
            .expect("tool")
    }

    #[test]
    fn bash_runs_and_reports() {
        let out = run(&Bash, json!({"command": "echo hello"}));
        assert!(out.text.contains("hello"));
    }

    #[test]
    fn bash_reports_exit_status() {
        let out = run(&Bash, json!({"command": "exit 7"}));
        assert!(out.text.contains("exit status 7"));
    }

    #[test]
    fn python_executes_code() {
        let out = run(&PythonExecute, json!({"code": "print(6*7)"}));
        assert!(out.text.contains("42"));
    }

    #[test]
    fn python_reports_stderr() {
        let out = run(
            &PythonExecute,
            json!({"code": "import sys; print('x', file=sys.stderr)"}),
        );
        assert!(out.text.contains('x'));
    }
}
