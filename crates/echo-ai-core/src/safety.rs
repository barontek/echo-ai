//! Safety policy: workspace pinning, path/command/domain checks, and
//! approval gating — the single enforcement point for "no escaping the
//! workspace, no approval bypass" (mirrors the C project's `safety.c`).
//!
//! The workspace pinning is the real security boundary; the blocklists
//! are best-effort conveniences that (a) replace the built-in defaults
//! when configured and (b) flag *obvious* destructive commands so the
//! human approver sees a prompt. They are explicitly not a sandbox.
//!
//! Depends on: crate `config`, crate `error`.

use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::time::Duration;

use crate::config;
use crate::error::{Error, Result};

/// Approval strictness.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SafetyMode {
    /// Default: tools on the approval list (or destructive commands)
    /// require human approval.
    Restricted,
    /// Every tool call requires approval.
    ApproveAll,
    /// No approvals, no command screening.
    Unrestricted,
}

impl SafetyMode {
    fn parse(s: &str) -> Self {
        match s {
            "approve_all" => Self::ApproveAll,
            "unrestricted" => Self::Unrestricted,
            _ => Self::Restricted,
        }
    }
}

/// Default blocked extensions (replaceable via config, C semantics).
const DEFAULT_BLOCKED_EXTENSIONS: &[&str] = &[
    ".key",
    ".pem",
    ".env",
    ".token",
    ".password",
    ".aws",
    ".netrc",
    ".htpasswd",
    ".crt",
    ".p12",
];

/// Default blocked path substrings (replaceable via config).
const DEFAULT_BLOCKED_PATHS: &[&str] =
    &["/etc/passwd", "/etc/shadow", "/etc/sudoers", ".git/config"];

/// Obvious destructive command fragments; a match forces approval in
/// Restricted mode (best-effort, not a sandbox).
const DANGEROUS_PATTERNS: &[&str] = &[
    "rm -rf /",
    "rm -rf /*",
    ":(){ :|:& };:",
    "fork()",
    "mkfs.",
    "mkswap",
    "dd if=",
    "dd if=/dev/zero",
    "dd if=/dev/urandom",
    "shred",
    "> /dev/sda",
    "> /dev/sdb",
    "> /dev/nvme",
    "pv < /dev/sda",
    "pv < /dev/sdb",
    "debugfs",
    "hdparm",
    "mount -o loop",
    "losetup",
    "parted",
    "fdisk",
    "cfdisk",
    "sfdisk",
    "chmod 777",
    "chmod -R 777",
    "sudo rm",
    "sudo rm -rf",
];

/// Destructive-keyword hints (same role as `DANGEROUS_PATTERNS`).
const DANGEROUS_KEYWORDS: &[&str] = &[
    "delete", "destroy", "format", "drop", "truncate", "shred", "wipe", "erase", "purge", "reset",
];

/// The effective safety policy. Built once from [`config::Safety`] plus
/// the resolved workspace; configured blocklists replace the defaults.
#[derive(Debug, Clone)]
pub struct SafetyConfig {
    /// Approval mode.
    pub mode: SafetyMode,
    /// Canonical workspace root; every resolved path must stay inside.
    pub workspace: PathBuf,
    /// Whether tools may reach the network.
    pub allow_network: bool,
    /// Largest file read/write tools will touch.
    pub max_file_size: u64,
    /// Character cap on `web_fetch` text extraction.
    pub web_fetch_max_chars: usize,
    /// Hard timeout for subprocess tools.
    pub max_execution_time: Duration,
    /// How long `ask_user` waits for an answer.
    pub ask_user_timeout: Duration,
    /// Tools whose calls require approval in Restricted mode.
    require_approval_for: HashSet<String>,
    /// Effective extension blocklist (suffix match).
    blocked_extensions: Vec<String>,
    /// Effective path-substring blocklist.
    blocked_paths: Vec<String>,
    /// Host blocklist for network tools (empty = no extra filtering).
    blocked_domains: Vec<String>,
}

impl SafetyConfig {
    /// Builds the policy from TOML config. `workspace` wins over the
    /// config value when provided (the server pins its own root).
    #[must_use]
    pub fn from_config(cfg: &config::Safety, workspace: Option<PathBuf>) -> Self {
        let workspace = if let Some(ws) = workspace {
            ws
        } else {
            let ws = PathBuf::from(&cfg.workspace);
            if ws.is_absolute() {
                ws
            } else if ws.as_os_str().is_empty() {
                std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
            } else {
                std::env::current_dir()
                    .unwrap_or_else(|_| PathBuf::from("."))
                    .join(ws)
            }
        };
        let workspace = canonicalize_or_absolute(&workspace);

        let blocked_extensions = if cfg.blocked_extensions.is_empty() {
            DEFAULT_BLOCKED_EXTENSIONS
                .iter()
                .map(|s| String::from(*s))
                .collect()
        } else {
            cfg.blocked_extensions.clone()
        };
        let blocked_paths = if cfg.blocked_paths.is_empty() {
            DEFAULT_BLOCKED_PATHS
                .iter()
                .map(|s| String::from(*s))
                .collect()
        } else {
            cfg.blocked_paths.clone()
        };
        let require_approval_for = cfg.require_approval_for.iter().cloned().collect();

        Self {
            mode: SafetyMode::parse(&cfg.mode),
            workspace,
            allow_network: cfg.allow_network,
            max_file_size: cfg.max_file_size,
            web_fetch_max_chars: cfg.web_fetch_max_chars,
            max_execution_time: Duration::from_secs(cfg.max_execution_time_secs),
            ask_user_timeout: Duration::from_secs(cfg.ask_user_timeout_secs),
            require_approval_for,
            blocked_extensions,
            blocked_paths,
            blocked_domains: Vec::new(),
        }
    }

    /// Resolves a (possibly relative, possibly symlinked) path and pins
    /// it inside the workspace. The deepest existing ancestor is
    /// canonicalized first, so targets that do not exist yet (writes)
    /// still resolve correctly.
    ///
    /// # Errors
    /// `Error::Safety` when the resolved path escapes the workspace.
    pub fn resolve_path(&self, path: &Path) -> Result<PathBuf> {
        let joined = if path.is_absolute() {
            path.to_path_buf()
        } else {
            self.workspace.join(path)
        };
        let resolved = canonicalize_deepest(&joined).unwrap_or(joined);
        if !resolved.starts_with(&self.workspace) {
            return Err(Error::Safety(format!(
                "path escapes workspace: {} (workspace: {})",
                resolved.display(),
                self.workspace.display()
            )));
        }
        Ok(resolved)
    }

    /// Validates a path against the blocklists and size cap (reads).
    ///
    /// # Errors
    /// `Error::Safety` on blocklisted extension/path, size overflow, or
    /// workspace escape.
    pub fn check_read(&self, path: &Path) -> Result<PathBuf> {
        let resolved = self.resolve_path(path)?;
        self.check_blocklists(&resolved)?;
        if let Ok(meta) = std::fs::metadata(&resolved)
            && meta.len() > self.max_file_size
        {
            return Err(Error::Safety(format!(
                "file too large: {} bytes (limit {})",
                meta.len(),
                self.max_file_size
            )));
        }
        Ok(resolved)
    }

    /// Validates a path for writes (blocklists only — the size cap is
    /// the writer's job since the target may not exist yet).
    ///
    /// # Errors
    /// `Error::Safety` on blocklisted extension/path or workspace
    /// escape.
    pub fn check_write(&self, path: &Path) -> Result<PathBuf> {
        let resolved = self.resolve_path(path)?;
        self.check_blocklists(&resolved)?;
        Ok(resolved)
    }

    fn check_blocklists(&self, resolved: &Path) -> Result<()> {
        let s = resolved.to_string_lossy();
        for ext in &self.blocked_extensions {
            if s.ends_with(ext.as_str()) {
                return Err(Error::Safety(format!(
                    "blocked extension {ext} on {}",
                    resolved.display()
                )));
            }
        }
        for pat in &self.blocked_paths {
            if s.contains(pat.as_str()) {
                return Err(Error::Safety(format!(
                    "blocked path pattern {pat} on {}",
                    resolved.display()
                )));
            }
        }
        Ok(())
    }

    /// Whether a command fragment matches the destructive screen.
    #[must_use]
    pub fn is_destructive(&self, command: &str) -> bool {
        if self.mode == SafetyMode::Unrestricted {
            return false;
        }
        DANGEROUS_PATTERNS.iter().any(|p| command.contains(p))
            || DANGEROUS_KEYWORDS.iter().any(|k| command.contains(k))
    }

    /// Whether a hostname is domain-blocked.
    /// Whether a hostname is domain-blocked.
    #[must_use]
    pub fn is_domain_blocked(&self, host: &str) -> bool {
        self.blocked_domains
            .iter()
            .any(|d| host == d || host.ends_with(&format!(".{d}")))
    }

    /// Whether a tool call needs human approval in the current mode.
    #[must_use]
    pub fn needs_approval(&self, tool: &str) -> bool {
        match self.mode {
            SafetyMode::Unrestricted => false,
            SafetyMode::ApproveAll => true,
            SafetyMode::Restricted => self.require_approval_for.contains(tool),
        }
    }

    /// Whether a command-carrying tool call needs approval (tool name +
    /// destructive-command screen).
    #[must_use]
    pub fn needs_approval_for_command(&self, tool: &str, command: &str) -> bool {
        self.needs_approval(tool) || self.is_destructive(command)
    }
}

/// Canonicalizes `p` if it exists, otherwise returns it as-is.
fn canonicalize_or_absolute(p: &Path) -> PathBuf {
    if let Ok(c) = p.canonicalize() {
        return c;
    }
    if p.is_absolute() {
        p.to_path_buf()
    } else if let Ok(cwd) = std::env::current_dir() {
        cwd.join(p)
    } else {
        p.to_path_buf()
    }
}

/// Canonicalizes the deepest existing ancestor of `p` and re-appends the
/// remainder (so not-yet-existing targets resolve through symlinked
/// parents). A fully-existing target canonicalizes as-is — joining an
/// empty remainder would append a trailing separator that breaks
/// suffix matching.
fn canonicalize_deepest(p: &Path) -> Option<PathBuf> {
    let mut ancestors: Vec<&Path> = p.ancestors().collect();
    ancestors.reverse();
    let mut existing = None;
    for a in &ancestors {
        if a.exists() {
            existing = Some(a);
        } else {
            break;
        }
    }
    let existing = existing?;
    let canon = existing.canonicalize().ok()?;
    let remainder = p.strip_prefix(existing).ok()?;
    if remainder.as_os_str().is_empty() {
        return Some(canon);
    }
    let mut out = canon;
    out.push(remainder);
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    static COUNTER: AtomicUsize = AtomicUsize::new(0);

    fn test_config(workspace: &Path) -> SafetyConfig {
        SafetyConfig::from_config(&config::Safety::default(), Some(workspace.to_path_buf()))
    }

    /// Unique per-test workspace: tests run in parallel within one
    /// process, and a shared dir name (same pid) would race.
    fn temp_workspace() -> PathBuf {
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir().join(format!("echo-safety-{}-{n}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("create temp workspace");
        dir
    }

    #[test]
    fn relative_paths_resolve_inside_workspace() {
        let ws = temp_workspace();
        let cfg = test_config(&ws);
        let resolved = cfg
            .resolve_path(Path::new("sub/file.txt"))
            .expect("resolve");
        assert!(resolved.starts_with(&ws));
        let _ = std::fs::remove_dir_all(&ws);
    }

    #[test]
    fn absolute_paths_escaped_rejected() {
        let ws = temp_workspace();
        let cfg = test_config(&ws);
        let err = cfg
            .resolve_path(Path::new("/etc/hostname"))
            .expect_err("must escape");
        assert!(matches!(err, Error::Safety(_)));
        let _ = std::fs::remove_dir_all(&ws);
    }

    #[test]
    fn dotdot_escape_rejected() {
        let ws = temp_workspace();
        let cfg = test_config(&ws);
        let err = cfg
            .resolve_path(Path::new("../../etc/passwd"))
            .expect_err("must escape");
        assert!(matches!(err, Error::Safety(_)));
        let _ = std::fs::remove_dir_all(&ws);
    }

    #[test]
    fn symlink_escape_rejected() {
        let ws = temp_workspace();
        let outside = std::env::temp_dir().join(format!(
            "echo-safety-out-{}-{}",
            std::process::id(),
            COUNTER.load(Ordering::SeqCst)
        ));
        std::fs::write(&outside, "secret").expect("write outside");
        #[cfg(unix)]
        std::os::unix::fs::symlink(&outside, ws.join("link")).expect("symlink");
        let cfg = test_config(&ws);
        let err = cfg
            .resolve_path(Path::new("link"))
            .expect_err("symlink must escape");
        assert!(matches!(err, Error::Safety(_)));
        let _ = std::fs::remove_file(&outside);
        let _ = std::fs::remove_dir_all(&ws);
    }

    #[test]
    fn default_blocklists_apply() {
        let ws = temp_workspace();
        let cfg = test_config(&ws);
        std::fs::write(ws.join("secrets.env"), "x").expect("write");
        let err = cfg
            .check_read(Path::new("secrets.env"))
            .expect_err("blocked ext");
        assert!(matches!(err, Error::Safety(_)));
        std::fs::create_dir_all(ws.join(".git")).expect("git dir");
        std::fs::write(ws.join(".git/config"), "x").expect("write");
        let err = cfg
            .check_read(Path::new(".git/config"))
            .expect_err("blocked path");
        assert!(matches!(err, Error::Safety(_)));
        let _ = std::fs::remove_dir_all(&ws);
    }

    #[test]
    fn configured_blocklist_replaces_defaults() {
        let ws = temp_workspace();
        let toml = config::Safety {
            blocked_extensions: vec![String::from(".txt")],
            ..Default::default()
        };
        let cfg = SafetyConfig::from_config(&toml, Some(ws.clone()));
        // .env is no longer blocked (defaults replaced)...
        std::fs::write(ws.join("a.env"), "x").expect("write");
        assert!(cfg.check_read(Path::new("a.env")).is_ok());
        // ...but .txt now is.
        std::fs::write(ws.join("b.txt"), "x").expect("write");
        assert!(cfg.check_read(Path::new("b.txt")).is_err());
        let _ = std::fs::remove_dir_all(&ws);
    }

    #[test]
    fn approval_gating_respects_mode() {
        let ws = temp_workspace();
        let mut toml = config::Safety {
            require_approval_for: vec![String::from("bash")],
            ..Default::default()
        };
        let cfg = SafetyConfig::from_config(&toml, Some(ws.clone()));
        assert!(cfg.needs_approval("bash"));
        assert!(!cfg.needs_approval("read_file"));
        assert!(cfg.needs_approval_for_command("read_file", "rm -rf /"));
        toml.mode = String::from("unrestricted");
        let cfg = SafetyConfig::from_config(&toml, Some(ws.clone()));
        assert!(!cfg.needs_approval("bash"));
        assert!(!cfg.is_destructive("rm -rf /"));
        toml.mode = String::from("approve_all");
        let cfg = SafetyConfig::from_config(&toml, Some(ws));
        assert!(cfg.needs_approval("read_file"));
    }
}
