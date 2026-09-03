//! Configuration: `TOML` file with serde-driven structs and per-section
//! defaults (AGENTS.md "Structure and modules" — one responsibility per
//! module; this file owns only the config surface, not parsing details).
//!
//! The C project used a custom `.conf` format; the port deliberately
//! switched to `TOML` (user decision) while keeping section names and
//! option semantics recognizable. A missing default config file loads
//! clean defaults; an explicitly-provided `--config` path must exist and
//! parse (fail-fast, checked by the bin crate before this module runs).
//!
//! Depends on: `serde`, `toml`, crate `error`.

use std::collections::BTreeMap;
use std::path::Path;

use serde::Deserialize;

use crate::error::{Error, Result};

/// Whole-file configuration. Every section defaults independently, so a
/// config file may contain only the sections the user cares about.
#[derive(Debug, Clone, Default, Deserialize)]
pub struct Config {
    /// Agent loop tuning.
    #[serde(default)]
    pub agent: Agent,
    /// Ollama provider.
    #[serde(default)]
    pub ollama: Ollama,
    /// `OpenAI` (`Codex`) provider — OAuth only, no API keys accepted.
    #[serde(default)]
    pub openai: OpenAi,
    /// `OpenAI`-compatible endpoints (`LM Studio`, `vLLM`, llama.cpp).
    #[serde(default)]
    pub openai_compatible: OpenAiCompatible,
    /// `OpenCode Zen` provider.
    #[serde(default)]
    pub opencode_zen: OpenCodeZen,
    /// `OpenCode Go` provider.
    #[serde(default)]
    pub opencode_go: OpenCodeGo,
    /// Safety policy.
    #[serde(default)]
    pub safety: Safety,
    /// Session persistence.
    #[serde(default)]
    pub session: Session,
    /// Tool enablement.
    #[serde(default)]
    pub tools: Tools,
    /// Browser tool.
    #[serde(default)]
    pub browser: Browser,
    /// Web search provider.
    #[serde(default)]
    pub search: Search,
    /// Bearer tokens per provider name (never the `openai` provider).
    #[serde(default)]
    pub providers: BTreeMap<String, String>,
    /// Web server.
    #[serde(default)]
    pub server: Server,
    /// TUI appearance.
    #[serde(default)]
    pub tui: Tui,
}

/// Agent loop tuning.
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct Agent {
    /// Provider name: `ollama`, `openai`, `openai_compatible`,
    /// `opencode_zen`, `opencode_go`.
    pub provider: String,
    /// Model name; required by providers that need one.
    pub model: String,
    /// Base system prompt (empty = provider default).
    pub system_prompt: String,
    /// Sampling temperature (0.0–2.0).
    pub temperature: f64,
    /// Per-request timeout in seconds.
    pub timeout_secs: u64,
    /// Reasoning effort hint (`low`/`medium`/`high`/`xhigh`/`max`/`none`).
    pub effort: String,
    /// Hard cap on loop iterations per run.
    pub max_iterations: usize,
    /// Maximum messages kept in the context window.
    pub max_context_messages: usize,
    /// Maximum characters kept in the context window.
    pub max_context_chars: usize,
    /// Cap on tool-result text fed back to the model.
    pub max_tool_result_chars: usize,
}

impl Default for Agent {
    fn default() -> Self {
        Self {
            provider: String::from("ollama"),
            model: String::new(),
            system_prompt: String::new(),
            temperature: 0.7,
            timeout_secs: 300,
            effort: String::from("medium"),
            max_iterations: 20,
            max_context_messages: 80,
            max_context_chars: 60_000,
            max_tool_result_chars: 8_000,
        }
    }
}

/// Ollama provider settings.
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct Ollama {
    /// Base URL of the Ollama server.
    pub base_url: String,
    /// Context window size requested from Ollama.
    pub num_ctx: u32,
    /// How long the model stays loaded after use.
    pub keep_alive_secs: u64,
}

impl Default for Ollama {
    fn default() -> Self {
        Self {
            base_url: String::from("http://localhost:11434"),
            num_ctx: 4096,
            keep_alive_secs: 120,
        }
    }
}

/// `OpenAI` (`Codex`) provider settings.
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct OpenAi {
    /// Device-flow OAuth only; no key material lives here.
    pub oauth: bool,
}

impl Default for OpenAi {
    fn default() -> Self {
        Self { oauth: true }
    }
}

/// `OpenAI`-compatible endpoint settings (`LM Studio`, `vLLM`, llama.cpp).
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct OpenAiCompatible {
    /// Base URL of the compatible server.
    pub base_url: String,
    /// Optional Bearer token; `[providers]` entries are preferred.
    pub token: String,
}

impl Default for OpenAiCompatible {
    fn default() -> Self {
        Self {
            base_url: String::from("http://localhost:1234"),
            token: String::new(),
        }
    }
}

/// `OpenCode Zen` provider.settings.
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct OpenCodeZen {
    /// Base URL of the Zen API.
    pub base_url: String,
}

impl Default for OpenCodeZen {
    fn default() -> Self {
        Self {
            base_url: String::from("https://opencode.ai/zen/v1"),
        }
    }
}

/// `OpenCode Go` provider settings.
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct OpenCodeGo {
    /// Base URL of the Go API.
    pub base_url: String,
}

impl Default for OpenCodeGo {
    fn default() -> Self {
        Self {
            base_url: String::from("https://opencode.ai/zen/go/v1"),
        }
    }
}

/// Path-safety and approval policy. Mirrors the C version's semantics:
/// configured blocklists *replace* the built-in defaults, and the
/// workspace pinning is the real security boundary, not the lists.
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct Safety {
    /// `restricted`, `approve_all`, or `unrestricted`.
    pub mode: String,
    /// Root of the agent's filesystem world (empty = current dir).
    pub workspace: String,
    /// Whether tools may reach the network.
    pub allow_network: bool,
    /// Largest file read/write tools will touch.
    pub max_file_size: u64,
    /// Character cap on `web_fetch` text extraction.
    pub web_fetch_max_chars: usize,
    /// Hard timeout for subprocess tools, in seconds.
    pub max_execution_time_secs: u64,
    /// Extension blocklist; empty = built-in defaults.
    pub blocked_extensions: Vec<String>,
    /// Path-substring blocklist; empty = built-in defaults.
    pub blocked_paths: Vec<String>,
    /// Tools that require human approval by default.
    pub require_approval_for: Vec<String>,
    /// How long `ask_user` waits for an answer, in seconds.
    pub ask_user_timeout_secs: u64,
}

impl Default for Safety {
    fn default() -> Self {
        Self {
            mode: String::from("restricted"),
            workspace: String::new(),
            allow_network: true,
            max_file_size: 10 * 1024 * 1024,
            web_fetch_max_chars: 25_000,
            max_execution_time_secs: 300,
            blocked_extensions: Vec::new(),
            blocked_paths: Vec::new(),
            require_approval_for: vec![
                String::from("bash"),
                String::from("write_file"),
                String::from("edit"),
                String::from("git"),
                String::from("python_execute"),
                String::from("delegate"),
            ],
            ask_user_timeout_secs: 60,
        }
    }
}

/// Session persistence.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct Session {
    /// Persist sessions to the data dir (enables setup/unlock).
    pub enabled: bool,
}

/// Tool enablement.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct Tools {
    /// Enabled tool names; empty = all tools enabled.
    pub enabled: Vec<String>,
}

/// Browser tool settings.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct Browser {
    /// Run the browser in headless mode.
    pub headless: bool,
}

/// Web search provider.
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct Search {
    /// `brave`, `duckduckgo`, or `tavily`.
    pub provider: String,
    /// API key for providers that need one.
    pub api_key: String,
}

impl Default for Search {
    fn default() -> Self {
        Self {
            provider: String::from("duckduckgo"),
            api_key: String::new(),
        }
    }
}

/// Web server settings.
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct Server {
    /// Listen port. `TLS` is on by default; the default port matches the
    /// C project's Caddy-fronted 8443.
    pub port: u16,
    /// Bind address; localhost by default now that `TLS` is built in.
    pub bind: String,
    /// Serve `HTTPS` (built-in rustls with an auto-generated local cert).
    pub tls: bool,
    /// Optional custom certificate (`PEM`); auto-generated when absent.
    pub tls_cert: String,
    /// Optional custom private key (`PEM`); auto-generated when absent.
    pub tls_key: String,
}

impl Default for Server {
    fn default() -> Self {
        Self {
            port: 8443,
            bind: String::from("127.0.0.1"),
            tls: true,
            tls_cert: String::new(),
            tls_key: String::new(),
        }
    }
}

/// TUI appearance.
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct Tui {
    /// `dark`, `light`, `highcontrast`, or `none`.
    pub style: String,
    /// `compact` or `spacious`.
    pub density: String,
    /// Accent color as `#rrggbb`.
    pub accent: String,
    /// Transparent background.
    pub transparent: bool,
    /// Keybinding overrides (`keymap_<action>` style names).
    pub keybindings: BTreeMap<String, String>,
}

impl Default for Tui {
    fn default() -> Self {
        Self {
            style: String::from("dark"),
            density: String::from("compact"),
            accent: String::from("#7aa2f7"),
            transparent: false,
            keybindings: BTreeMap::new(),
        }
    }
}

impl Config {
    /// Loads a config file.
    ///
    /// # Errors
    /// Returns `Error::Config` when the file exists but cannot be read
    /// or parsed; a missing file yields clean defaults instead.
    pub fn load(path: &Path) -> Result<Self> {
        let text = match std::fs::read_to_string(path) {
            Ok(text) => text,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Self::default()),
            Err(e) => {
                return Err(Error::Io {
                    path: path.into(),
                    source: e,
                });
            }
        };
        toml::from_str(&text).map_err(|e| Error::Config(e.to_string()))
    }

    /// The effective workspace root: the configured value, or the
    /// current directory when unset.
    #[must_use]
    pub fn effective_workspace(&self) -> std::path::PathBuf {
        let ws = &self.safety.workspace;
        if ws.is_empty() {
            match std::env::current_dir() {
                Ok(cwd) => cwd,
                Err(_) => std::path::PathBuf::from("."),
            }
        } else {
            std::path::PathBuf::from(ws)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_apply_without_any_config_file() {
        let dir = std::env::temp_dir().join("echo-ai-config-nonexistent.toml");
        let cfg = Config::load(&dir).expect("missing file loads defaults");
        assert_eq!(cfg.agent.provider, "ollama");
        assert_eq!(cfg.server.port, 8443);
        assert!(cfg.server.tls);
        assert_eq!(cfg.safety.mode, "restricted");
        assert_eq!(cfg.tools.enabled.len(), 0);
    }

    #[test]
    fn parses_partial_file_with_defaults_for_rest() {
        let text = r#"
            [agent]
            provider = "openai_compatible"
            model = "qwen3-coder"
            temperature = 1.1

            [safety]
            blocked_extensions = [".db"]
        "#;
        let cfg: Config = toml::from_str(text).expect("parse");
        assert_eq!(cfg.agent.provider, "openai_compatible");
        assert!((cfg.agent.temperature - 1.1).abs() < f64::EPSILON);
        assert_eq!(cfg.safety.blocked_extensions, vec![String::from(".db")]);
        // Untouched sections keep defaults:
        assert_eq!(cfg.ollama.base_url, "http://localhost:11434");
        assert_eq!(cfg.server.bind, "127.0.0.1");
    }

    #[test]
    fn rejects_malformed_toml() {
        let dir = std::env::temp_dir();
        let path = dir.join("echo-ai-config-malformed.toml");
        std::fs::write(&path, "[agent\nprovider = ").expect("write");
        let err = Config::load(&path).expect_err("malformed must fail");
        assert!(matches!(err, Error::Config(_)));
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn providers_table_carries_tokens() {
        let text = r#"
            [providers]
            opencode = "tok-123"
            openai_compatible = "tok-456"
        "#;
        let cfg: Config = toml::from_str(text).expect("parse");
        assert_eq!(
            cfg.providers.get("opencode").map(String::as_str),
            Some("tok-123")
        );
    }
}
