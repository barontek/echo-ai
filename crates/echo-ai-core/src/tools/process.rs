//! Subprocess runner: spawns with its own process group and enforces a
//! hard timeout by killing the whole group.
//!
//! The process group is the portability-relevant part (AGENTS.md
//! "Cross-platform portability"): `Command::process_group(0)` exists on
//! both Linux and macOS, and the kill path behind `cfg(unix)` uses
//! `libc::killpg` with the child's pid as the group id — the CI macOS
//! job compiles and exercises this exact code.
//!
//! Depends on: `tokio`, `libc`, crate `tools::tool`.

use std::path::Path;
use std::time::Duration;

use tokio::io::AsyncReadExt;
use tokio::process::Command;

use super::tool::ToolError;

/// Captured subprocess result.
#[derive(Debug, Clone)]
pub struct CommandOutput {
    /// Exit status code (`-1` when killed by signal or timeout).
    pub status: i32,
    /// `stdout` (lossy UTF-8, capped).
    pub stdout: String,
    /// `stderr` (lossy UTF-8, capped).
    pub stderr: String,
    /// Whether the timeout fired and the process group was killed.
    pub timed_out: bool,
}

/// Captured-output cap (keeps tool results within the model budget).
const OUTPUT_CAP: usize = 64 * 1024;

/// Runs `program` with `args`, capturing output and enforcing `timeout`
/// by killing the child's process group.
///
/// # Errors
/// `ToolError::Execution` on spawn failure; `ToolError::Timeout` when
/// the time limit is hit (the whole group is killed first).
pub async fn run_command(
    program: &str,
    args: &[&str],
    timeout: Duration,
    cwd: Option<&Path>,
) -> Result<CommandOutput, ToolError> {
    let mut command = Command::new(program);
    command
        .args(args)
        .kill_on_drop(true)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    if let Some(dir) = cwd {
        command.current_dir(dir);
    }
    // Unix: the child becomes its own process-group leader, so killing
    // the group later catches every descendant, not just the direct
    // child. Present on Linux and macOS; guarded for other platforms.
    #[cfg(unix)]
    command.process_group(0);

    let mut child = command
        .spawn()
        .map_err(|e| ToolError::Execution(format!("spawn {program}: {e}")))?;
    let pid = child.id();
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();

    let wait_fut = child.wait();
    tokio::pin!(wait_fut);
    let status = tokio::select! {
        s = &mut wait_fut => s.map_err(|e| ToolError::Execution(format!("wait {program}: {e}")))?,
        () = tokio::time::sleep(timeout) => {
            if let Some(pid) = pid {
                kill_group(pid);
            }
            // Briefly let the group die so its pipes close, then report.
            let _ = tokio::time::timeout(Duration::from_secs(2), &mut wait_fut).await;
            return Err(ToolError::Timeout(timeout));
        }
    };

    let mut stdout_buf = Vec::new();
    let mut stderr_buf = Vec::new();
    if let Some(mut s) = stdout {
        let _ = tokio::time::timeout(Duration::from_secs(5), s.read_to_end(&mut stdout_buf)).await;
    }
    if let Some(mut s) = stderr {
        let _ = tokio::time::timeout(Duration::from_secs(5), s.read_to_end(&mut stderr_buf)).await;
    }

    Ok(CommandOutput {
        status: status.code().unwrap_or(-1),
        stdout: lossy_cap(&stdout_buf),
        stderr: lossy_cap(&stderr_buf),
        timed_out: false,
    })
}

/// Kills the process group whose id is `pgid`.
///
/// # Safety
/// Callers pass the pid of a child spawned with `process_group(0)` (see
/// `run_command`), so it is both the child's pid and its process group
/// id; `killpg` then signals exactly that group — the child and any
/// descendants it spawned. The pid cannot be recycled while the child
/// handle is alive (it is), and `killpg` returns `ESRCH` harmlessly if
/// the group already exited. `libc::killpg` is available on all Unix
/// targets this crate builds for (Linux, macOS).
#[cfg(unix)]
fn kill_group(pgid: u32) {
    // SAFETY: see the doc above — the caller's pid is the process-group
    // leader's id because the child was spawned with `process_group(0)`.
    let _ = unsafe { libc::killpg(pgid as libc::pid_t, libc::SIGKILL) };
}

/// No-op on non-Unix (the tool runner is Unix-only in practice).
#[cfg(not(unix))]
fn kill_group(_pgid: u32) {}

/// Lossy UTF-8 decode with a hard output cap.
fn lossy_cap(bytes: &[u8]) -> String {
    let text = String::from_utf8_lossy(bytes);
    if text.len() > OUTPUT_CAP {
        let mut s: String = text.chars().take(OUTPUT_CAP).collect();
        s.push_str("\n...[truncated]");
        s
    } else {
        text.into_owned()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn captures_output_and_status() {
        let out = run_command(
            "sh",
            &["-c", "echo hello; echo err >&2; exit 3"],
            Duration::from_secs(10),
            None,
        )
        .await
        .expect("run");
        assert_eq!(out.status, 3);
        assert!(out.stdout.contains("hello"));
        assert!(out.stderr.contains("err"));
    }

    #[tokio::test]
    async fn timeout_kills_process_group() {
        let start = std::time::Instant::now();
        let err = run_command("sh", &["-c", "sleep 30"], Duration::from_millis(300), None)
            .await
            .expect_err("must time out");
        assert!(matches!(err, ToolError::Timeout(_)), "got {err:?}");
        assert!(start.elapsed() < Duration::from_secs(10), "killed promptly");
    }

    #[tokio::test]
    async fn timeout_kills_descendants_too() {
        // The child spawns a grandchild that outlives it; killing the
        // group must catch both.
        let err = run_command(
            "sh",
            &["-c", "sleep 30 & sleep 30"],
            Duration::from_millis(300),
            None,
        )
        .await
        .expect_err("must time out");
        assert!(matches!(err, ToolError::Timeout(_)));
    }

    #[tokio::test]
    async fn missing_program_is_execution_error() {
        let err = run_command(
            "/nonexistent/echo-ai-no-such-binary",
            &[],
            Duration::from_secs(5),
            None,
        )
        .await
        .expect_err("spawn must fail");
        assert!(matches!(err, ToolError::Execution(_)));
    }
}
