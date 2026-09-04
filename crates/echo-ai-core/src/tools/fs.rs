//! Filesystem tools: `read_file`, `write_file`, `edit`, `list_dir`,
//! `glob`, `grep`.
//!
//! Every path is resolved and pinned through the safety policy before
//! touching the disk; writes snapshot into the change tracker first
//! (undo support). One subsystem module rather than six files — the C
//! version's per-tool split was a file-length artifact.
//!
//! Depends on: `glob`, `tokio`, crate `safety`, `change_tracker`,
//! `tools::tool`.

use futures_util::future::BoxFuture;
use serde_json::{Value, json};
use std::path::{Path, PathBuf};

use crate::change_tracker::FileSnapshot;
use crate::error::Result;

use super::tool::{
    Tool, ToolContext, ToolError, ToolOutput, arg_optional_string, arg_optional_u64, arg_string,
};

/// Shared helper: resolved read path (safety checks included).
fn read_path<'a>(ctx: &'a ToolContext<'a>, path: &str) -> Result<PathBuf, ToolError> {
    ctx.safety
        .check_read(Path::new(path))
        .map_err(|e| ToolError::Safety(e.to_string()))
}

/// Shared helper: resolved write path + change-tracker snapshot.
fn write_path(ctx: &ToolContext<'_>, path: &str) -> Result<PathBuf, ToolError> {
    let resolved = ctx
        .safety
        .check_write(Path::new(path))
        .map_err(|e| ToolError::Safety(e.to_string()))?;
    if let Some(tracker) = ctx.change_tracker {
        let snapshot = FileSnapshot::capture(&resolved).ok();
        if let Some(s) = snapshot {
            let mut lock = tracker
                .lock()
                .map_err(|_| ToolError::Execution(String::from("change tracker lock poisoned")))?;
            let _ = lock.track(s);
        }
    }
    Ok(resolved)
}

/// `read_file`: reads a file, optionally within a line window.
pub struct ReadFile;

impl Tool for ReadFile {
    fn name(&self) -> &'static str {
        "read_file"
    }

    fn description(&self) -> &'static str {
        "Read a file's contents. Use line_start/line_end for a window; set continuation=true after a truncated read to continue where it stopped."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the workspace"},
                "line_start": {"type": "integer", "description": "1-based first line"},
                "line_end": {"type": "integer", "description": "1-based last line (inclusive)"}
            },
            "required": ["path"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            let path = arg_string(&args, "path")?;
            let resolved = read_path(ctx, &path)?;
            // Size cap from the safety policy (compatible:
            // `max_file_size`).
            if let Ok(meta) = std::fs::metadata(&resolved)
                && ctx.safety.max_file_size > 0
                && meta.len() > ctx.safety.max_file_size
            {
                return Err(ToolError::Safety(format!(
                    "file exceeds max_file_size ({} > {})",
                    meta.len(),
                    ctx.safety.max_file_size
                )));
            }
            let contents = std::fs::read_to_string(&resolved).map_err(|e| ToolError::Io {
                path: resolved.clone(),
                source: e,
            })?;
            let line_start = arg_optional_u64(&args, "line_start")
                .and_then(|v| usize::try_from(v).ok())
                .unwrap_or(1)
                .max(1);
            let line_end =
                arg_optional_u64(&args, "line_end").and_then(|v| usize::try_from(v).ok());
            let lines: Vec<&str> = contents.lines().collect();
            let total = lines.len();
            let start = line_start.saturating_sub(1).min(total);
            let end = line_end.map_or(total, |e| e.min(total));
            let selected = lines[start..end].join("\n");
            let truncated = end < total;
            let mut text = selected;
            if truncated {
                use std::fmt::Write as _;
                let _ = writeln!(
                    text,
                    "\n\n[truncated: showing lines {line_start}-{end} of {total}; pass line_start={} to continue]",
                    end + 1
                );
            }
            Ok(ToolOutput::text(text))
        })
    }
}

/// `write_file`: writes a file, creating parent directories.
pub struct WriteFile;

impl Tool for WriteFile {
    fn name(&self) -> &'static str {
        "write_file"
    }

    fn description(&self) -> &'static str {
        "Write a file (creating parent directories). Overwrites existing content."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            let path = arg_string(&args, "path")?;
            let content = arg_string(&args, "content")?;
            let resolved = write_path(ctx, &path)?;
            if let Some(parent) = resolved.parent()
                && !parent.as_os_str().is_empty()
            {
                std::fs::create_dir_all(parent).map_err(|e| ToolError::Io {
                    path: parent.to_path_buf(),
                    source: e,
                })?;
            }
            std::fs::write(&resolved, content.as_bytes()).map_err(|e| ToolError::Io {
                path: resolved.clone(),
                source: e,
            })?;
            Ok(ToolOutput::text(format!(
                "wrote {} bytes to {}",
                content.len(),
                resolved.display()
            )))
        })
    }
}

/// `edit`: exact unique-string replacement with atomic write.
pub struct Edit;

impl Tool for Edit {
    fn name(&self) -> &'static str {
        "edit"
    }

    fn description(&self) -> &'static str {
        "Replace an exact string occurrence in a file. The old_string must appear exactly once."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"}
            },
            "required": ["path", "old_string", "new_string"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            let path = arg_string(&args, "path")?;
            let old = arg_string(&args, "old_string")?;
            let new = arg_string(&args, "new_string")?;
            let resolved = write_path(ctx, &path)?;
            let contents = std::fs::read_to_string(&resolved).map_err(|e| ToolError::Io {
                path: resolved.clone(),
                source: e,
            })?;
            let count = contents.matches(&old).count();
            if count == 0 {
                return Err(ToolError::InvalidArgs(format!(
                    "old_string not found in {}",
                    resolved.display()
                )));
            }
            if count > 1 {
                return Err(ToolError::InvalidArgs(format!(
                    "old_string appears {count} times — include more surrounding context"
                )));
            }
            let updated = contents.replace(&old, &new);
            atomic_write(&resolved, updated.as_bytes())?;
            Ok(ToolOutput::text("edit applied"))
        })
    }
}

/// `list_dir`: sorted directory listing.
pub struct ListDir;

impl Tool for ListDir {
    fn name(&self) -> &'static str {
        "list_dir"
    }

    fn description(&self) -> &'static str {
        "List a directory's entries (one per line, directories marked with /)."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."}
            }
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            let path = arg_optional_string(&args, "path").unwrap_or_else(|| String::from("."));
            let resolved = read_path(ctx, &path)?;
            let mut entries: Vec<String> = std::fs::read_dir(&resolved)
                .map_err(|e| ToolError::Io {
                    path: resolved.clone(),
                    source: e,
                })?
                .filter_map(Result::ok)
                .map(|e| {
                    let name = e.file_name().to_string_lossy().into_owned();
                    let dir = e.path().is_dir();
                    if dir { format!("{name}/") } else { name }
                })
                .collect();
            entries.sort();
            if entries.is_empty() {
                return Ok(ToolOutput::text(format!(
                    "(empty directory: {})",
                    resolved.display()
                )));
            }
            Ok(ToolOutput::text(entries.join("\n")))
        })
    }
}

/// `glob`: workspace-relative glob expansion.
pub struct Glob;

impl Tool for Glob {
    fn name(&self) -> &'static str {
        "glob"
    }

    fn description(&self) -> &'static str {
        "Expand a glob pattern (e.g. src/**/*.rs) within the workspace."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "pattern": {"type": "string"}
            },
            "required": ["pattern"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            let pattern = arg_string(&args, "pattern")?;
            let joined = ctx.safety.workspace.join(&pattern);
            let pattern_str = joined.to_string_lossy().into_owned();
            let mut matches = Vec::new();
            let paths = glob::glob(&pattern_str)
                .map_err(|e| ToolError::InvalidArgs(format!("bad glob: {e}")))?;
            for entry in paths.flatten() {
                // Drop anything the safety policy would reject (escape
                // or blocklist) — glob must not leak out of workspace.
                if ctx.safety.check_read(&entry).is_ok() {
                    matches.push(entry);
                }
            }
            matches.sort();
            if matches.is_empty() {
                return Ok(ToolOutput::text(format!("no matches for {pattern}")));
            }
            let text = matches
                .iter()
                .map(|p| {
                    p.strip_prefix(&ctx.safety.workspace)
                        .unwrap_or(p)
                        .display()
                        .to_string()
                })
                .collect::<Vec<_>>()
                .join("\n");
            Ok(ToolOutput::text(text))
        })
    }
}

/// `grep`: recursive content search.
pub struct Grep;

impl Tool for Grep {
    fn name(&self) -> &'static str {
        "grep"
    }

    fn description(&self) -> &'static str {
        "Recursively search file contents for a pattern (skips symlinks and binary files)."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."}
            },
            "required": ["pattern"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            let pattern = arg_string(&args, "pattern")?;
            let path = arg_optional_string(&args, "path").unwrap_or_else(|| String::from("."));
            let resolved = read_path(ctx, &path)?;
            let mut hits = Vec::new();
            let mut stack = vec![resolved];
            while let Some(dir) = stack.pop() {
                let Ok(entries) = std::fs::read_dir(&dir) else {
                    continue;
                };
                for entry in entries.flatten() {
                    let p = entry.path();
                    if p.is_symlink() {
                        continue;
                    }
                    if p.is_dir() {
                        stack.push(p);
                    } else if ctx.safety.check_read(&p).is_ok()
                        && !is_binary(&p)
                        && let Ok(text) = std::fs::read_to_string(&p)
                        && let Some(line) = text.lines().find(|l| l.contains(&pattern))
                    {
                        hits.push(format!("{}: {}", rel(ctx, &p), line.trim()));
                        if hits.len() >= 200 {
                            return Ok(ToolOutput::text(format!(
                                "{} matches (truncated):\n{}",
                                hits.len(),
                                hits.join("\n")
                            )));
                        }
                    }
                }
            }
            if hits.is_empty() {
                return Ok(ToolOutput::text(format!("no matches for {pattern}")));
            }
            Ok(ToolOutput::text(hits.join("\n")))
        })
    }
}

/// Whether a file looks binary (NUL byte in the first 8 KiB).
fn is_binary(p: &Path) -> bool {
    let Ok(bytes) = std::fs::read(p) else {
        return true;
    };
    bytes.iter().take(8192).any(|b| *b == 0)
}

/// Workspace-relative display path.
fn rel(ctx: &ToolContext<'_>, p: &Path) -> String {
    p.strip_prefix(&ctx.safety.workspace)
        .unwrap_or(p)
        .display()
        .to_string()
}

/// Writes via temp file + rename (atomic on the same filesystem).
fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), ToolError> {
    let tmp = path.with_extension(format!("tmp-{}", std::process::id()));
    std::fs::write(&tmp, bytes).map_err(|e| ToolError::Io {
        path: tmp.clone(),
        source: e,
    })?;
    std::fs::rename(&tmp, path).map_err(|e| ToolError::Io {
        path: path.to_path_buf(),
        source: e,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::change_tracker::ChangeTracker;
    use crate::config::Config;
    use crate::safety::SafetyConfig;
    use std::sync::Arc;
    use std::sync::atomic::{AtomicUsize, Ordering};

    static COUNTER: AtomicUsize = AtomicUsize::new(0);

    fn ctx<'a>(
        safety: &'a SafetyConfig,
        tracker: Option<&'a Arc<std::sync::Mutex<ChangeTracker>>>,
        config: &'a Config,
    ) -> ToolContext<'a> {
        ToolContext {
            safety,
            config,
            session: None,
            change_tracker: tracker,
            ask_user: None,
            http: std::sync::Arc::new(crate::llm::http::ReqwestClient::new()),
        }
    }

    fn setup() -> (SafetyConfig, std::path::PathBuf) {
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir().join(format!("echo-fs-{}-{n}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("dir");
        let safety = SafetyConfig::from_config(&Config::default().safety, Some(dir.clone()));
        (safety, dir)
    }

    fn run<T: Tool>(tool: &T, args: Value, ctx: &ToolContext<'_>) -> ToolOutput {
        tokio::runtime::Runtime::new()
            .expect("rt")
            .block_on(tool.execute(args, ctx))
            .expect("tool")
    }

    #[test]
    fn read_write_edit_roundtrip() {
        let (safety, dir) = setup();
        let tracker = Arc::new(std::sync::Mutex::new(ChangeTracker::new()));
        let config = Config::default();
        let ctx = ctx(&safety, Some(&tracker), &config);
        run(
            &WriteFile,
            json!({"path": "a.txt", "content": "hello world"}),
            &ctx,
        );
        let out = run(&ReadFile, json!({"path": "a.txt"}), &ctx);
        assert!(out.text.contains("hello world"));
        // Undo is available after the write.
        assert!(tracker.lock().expect("lock").can_undo());
        run(
            &Edit,
            json!({"path": "a.txt", "old_string": "hello", "new_string": "goodbye"}),
            &ctx,
        );
        let out = run(&ReadFile, json!({"path": "a.txt"}), &ctx);
        assert!(out.text.contains("goodbye world"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn edit_requires_unique_old_string() {
        let (safety, dir) = setup();
        let config = Config::default();
        let ctx = ctx(&safety, None, &config);
        run(
            &WriteFile,
            json!({"path": "b.txt", "content": "x y x"}),
            &ctx,
        );
        let err = tokio::runtime::Runtime::new()
            .expect("rt")
            .block_on(Edit.execute(
                json!({"path": "b.txt", "old_string": "x", "new_string": "z"}),
                &ctx,
            ))
            .expect_err("ambiguous");
        assert!(matches!(err, ToolError::InvalidArgs(_)));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn escape_rejected_by_safety() {
        let (safety, dir) = setup();
        let config = Config::default();
        let ctx = ctx(&safety, None, &config);
        let err = tokio::runtime::Runtime::new()
            .expect("rt")
            .block_on(ReadFile.execute(json!({"path": "/etc/hostname"}), &ctx))
            .expect_err("escape");
        assert!(matches!(err, ToolError::Safety(_)));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn glob_stays_in_workspace() {
        let (safety, dir) = setup();
        let config = Config::default();
        let ctx = ctx(&safety, None, &config);
        run(
            &WriteFile,
            json!({"path": "sub/one.rs", "content": "x"}),
            &ctx,
        );
        run(
            &WriteFile,
            json!({"path": "sub/two.rs", "content": "x"}),
            &ctx,
        );
        let out = run(&Glob, json!({"pattern": "sub/*.rs"}), &ctx);
        assert!(out.text.contains("one.rs"));
        assert!(out.text.contains("two.rs"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn grep_finds_lines() {
        let (safety, dir) = setup();
        let config = Config::default();
        let ctx = ctx(&safety, None, &config);
        run(
            &WriteFile,
            json!({"path": "src/main.rs", "content": "fn main() {\n    let x = 1;\n}"}),
            &ctx,
        );
        let out = run(&Grep, json!({"pattern": "let x"}), &ctx);
        assert!(out.text.contains("main.rs"));
        assert!(out.text.contains("let x"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn read_file_line_window() {
        let (safety, dir) = setup();
        let config = Config::default();
        let ctx = ctx(&safety, None, &config);
        run(
            &WriteFile,
            json!({"path": "w.txt", "content": "a\nb\nc\nd"}),
            &ctx,
        );
        let out = run(
            &ReadFile,
            json!({"path": "w.txt", "line_start": 2, "line_end": 3}),
            &ctx,
        );
        assert!(out.text.starts_with("b\nc"), "got: {}", out.text);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
