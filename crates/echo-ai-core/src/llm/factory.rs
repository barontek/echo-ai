//! Provider factory: config-driven construction of the configured
//! provider (the original implementation's `factory.c` catalog).
//!
//! Depends on: crate `config`, `llm::{http,ollama,openai,openai_compatible,opencode,provider}`.

use std::sync::Arc;

use crate::config::Config;
use crate::error::{Error, Result};

use super::http::{HttpClient, ReqwestClient};
use super::ollama::Ollama;
use super::openai::OpenAi;
use super::openai_compatible::OpenAiCompatible;
use super::opencode::{OpenCodeGo, OpenCodeZen};
use super::provider::LlmProvider;

/// All supported provider catalog names.
pub const PROVIDERS: &[&str] = &[
    "ollama",
    "openai",
    "openai_compatible",
    "opencode_zen",
    "opencode_go",
];

/// Constructs the configured provider.
///
/// `codex_token` supplies the Codex OAuth token from the session vault;
/// the `openai` provider is unavailable without it.
///
/// # Errors
/// `Error::Unknown` for unknown provider names; `Error::Config` when a
/// required token is missing.
pub fn create_provider(
    cfg: &Config,
    http: Option<Arc<dyn HttpClient>>,
    codex_token: Option<String>,
) -> Result<Arc<dyn LlmProvider>> {
    let http: Arc<dyn HttpClient> = http.unwrap_or_else(|| Arc::new(ReqwestClient::new()));
    let name = cfg.agent.provider.as_str();
    match name {
        "ollama" => Ok(Arc::new(Ollama::new(cfg.ollama.base_url.clone(), http))),
        "openai" => {
            let token = codex_token.filter(|t| !t.is_empty()).ok_or_else(|| {
                Error::Config(String::from(
                    "openai provider requires a stored OAuth token (run the login flow)",
                ))
            })?;
            Ok(Arc::new(OpenAi::new(token, http)))
        }
        "openai_compatible" | "lmstudio" => {
            let token = cfg
                .providers
                .get("openai_compatible")
                .cloned()
                .filter(|t| !t.is_empty())
                .or_else(|| {
                    let t = cfg.openai_compatible.token.clone();
                    if t.is_empty() { None } else { Some(t) }
                });
            Ok(Arc::new(OpenAiCompatible::new(
                cfg.openai_compatible.base_url.clone(),
                token,
                http,
            )))
        }
        "opencode_zen" => {
            let token = cfg
                .providers
                .get("opencode")
                .cloned()
                .filter(|t| !t.is_empty())
                .ok_or_else(|| {
                    Error::Config(String::from(
                        "opencode_zen requires a token under [providers] opencode",
                    ))
                })?;
            Ok(Arc::new(OpenCodeZen::new(
                cfg.opencode_zen.base_url.clone(),
                token,
                http,
            )))
        }
        "opencode_go" => {
            let token = cfg
                .providers
                .get("opencode")
                .cloned()
                .filter(|t| !t.is_empty())
                .ok_or_else(|| {
                    Error::Config(String::from(
                        "opencode_go requires a token under [providers] opencode",
                    ))
                })?;
            Ok(Arc::new(OpenCodeGo::new(
                cfg.opencode_go.base_url.clone(),
                token,
                http,
            )))
        }
        other => Err(Error::Unknown {
            what: String::from("provider"),
            value: String::from(other),
        }),
    }
}

/// Resolves the model-list base URL for a provider from config.
///
/// Mirrors `create_provider`'s per-provider URL selection; unknown
/// providers fall back to the `openai_compatible` URL (the pre-existing
/// behavior, harmless since `list_models` rejects them anyway).
#[must_use]
pub fn models_base_url(cfg: &Config, provider: &str) -> String {
    match provider {
        "ollama" => cfg.ollama.base_url.clone(),
        "opencode_zen" => cfg.opencode_zen.base_url.clone(),
        "opencode_go" => cfg.opencode_go.base_url.clone(),
        _ => cfg.openai_compatible.base_url.clone(),
    }
}

/// Builds the models-list URL for a provider base URL.
///
/// Accepts both `http://host:port` and `http://host:port/v1`. The
/// trailing `/v1` is kept when present: opencode hosts carry a real
/// path before it (`/zen/go/v1`), so trimming it produces a 404.
#[must_use]
fn models_url(base_url: &str) -> String {
    let base = base_url.trim_end_matches('/');
    if base.ends_with("/v1") {
        format!("{base}/models")
    } else {
        format!("{base}/v1/models")
    }
}

/// Stable process-wide fallback for `x-opencode-session` on requests
/// with no conversation context (model listing). Per-conversation ids
/// are preferred everywhere a session id exists; this only guarantees
/// the header is present.
static OPENCODE_SESSION: std::sync::OnceLock<String> = std::sync::OnceLock::new();

fn opencode_session() -> &'static str {
    OPENCODE_SESSION.get_or_init(|| {
        let mut bytes = [0u8; 16];
        rand::RngCore::fill_bytes(&mut rand::thread_rng(), &mut bytes);
        let mut out = String::with_capacity(32);
        for b in bytes {
            let _ = std::fmt::Write::write_fmt(&mut out, format_args!("{b:02x}"));
        }
        out
    })
}

/// Builds the request headers for a provider's model-list call.
/// `OpenCode` hosts additionally carry the session-attribution headers
/// `OpenCode Go` requires on all API requests.
fn models_headers(provider: &str, token: Option<&str>) -> Vec<(&'static str, String)> {
    let mut headers: Vec<(&'static str, String)> = token
        .map(|t| vec![("Authorization", String::from(t))])
        .unwrap_or_default();
    if matches!(provider, "opencode_zen" | "opencode_go") {
        headers.push(("x-opencode-session", String::from(opencode_session())));
        headers.push(("x-opencode-client", String::from("echo-ai")));
    }
    headers
}

/// Fetches the live model list for a provider (used by the server's
/// `/api/models` and the TUI model picker).
///
/// # Errors
/// `Error::Unknown` for unknown providers; transport errors for
/// reachable ones.
pub async fn list_models(
    provider: &str,
    base_url: &str,
    token: Option<&str>,
    http: &dyn HttpClient,
) -> Result<Vec<String>> {
    let base = base_url.trim_end_matches('/');
    let owned = models_headers(provider, token);
    let headers: Vec<(&str, &str)> = owned
        .iter()
        .map(|(k, v)| (*k, v.as_str()))
        .collect();
    match provider {
        "ollama" => {
            let url = format!("{base}/api/tags");
            let json = http
                .post_json(&url, &[], serde_json::json!({}))
                .await
                .map_err(|e| Error::Session(e.to_string()))?;
            let mut models = Vec::new();
            if let Some(arr) = json.get("models").and_then(|m| m.as_array()) {
                for m in arr {
                    if let Some(name) = m.get("name").and_then(|n| n.as_str()) {
                        models.push(String::from(name));
                    }
                }
            }
            Ok(models)
        }
        "openai_compatible" | "opencode_zen" | "opencode_go" => {
            let url = models_url(base_url);
            let json = http
                .get_json(&url, &headers)
                .await
                .map_err(|e| Error::Session(e.to_string()))?;
            let mut models = Vec::new();
            if let Some(arr) = json.get("data").and_then(|d| d.as_array()) {
                for m in arr {
                    if let Some(id) = m.get("id").and_then(|i| i.as_str()) {
                        models.push(String::from(id));
                    }
                }
            }
            Ok(models)
        }
        other => Err(Error::Unknown {
            what: String::from("provider"),
            value: String::from(other),
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cfg_with(provider: &str) -> Config {
        let mut cfg = Config::default();
        cfg.agent.provider = String::from(provider);
        cfg
    }

    #[test]
    fn factory_resolves_all_catalog_names() {
        let http: Arc<dyn HttpClient> = Arc::new(ReqwestClient::new());
        for name in ["ollama", "openai_compatible"] {
            let cfg = cfg_with(name);
            let p = create_provider(&cfg, Some(http.clone()), None).expect("provider");
            assert_eq!(p.name(), name);
        }
        let mut zen_cfg = cfg_with("opencode_zen");
        zen_cfg
            .providers
            .insert(String::from("opencode"), String::from("t"));
        let p = create_provider(&zen_cfg, Some(http.clone()), None).expect("zen");
        assert_eq!(p.name(), "opencode_zen");
        let go_cfg = zen_cfg.clone(); // same token entry
        let mut go_cfg = go_cfg;
        go_cfg.agent.provider = String::from("opencode_go");
        let p = create_provider(&go_cfg, Some(http.clone()), None).expect("go");
        assert_eq!(p.name(), "opencode_go");
        // Codex without a token fails cleanly.
        let openai_cfg = cfg_with("openai");
        let Err(err) = create_provider(&openai_cfg, Some(http), None) else {
            panic!("expected error for tokenless codex");
        };
        assert!(matches!(err, Error::Config(_)));
    }

    #[test]
    fn unknown_provider_rejected() {
        let cfg = cfg_with("totally_not_a_provider");
        let Err(err) = create_provider(&cfg, None, None) else {
            panic!("expected unknown-provider error");
        };
        assert!(matches!(err, Error::Unknown { .. }));
    }

    #[test]
    fn opencode_without_token_rejected() {
        let cfg = cfg_with("opencode_zen");
        let Err(err) = create_provider(&cfg, None, None) else {
            panic!("expected token error");
        };
        assert!(matches!(err, Error::Config(_)));
    }

    #[test]
    fn models_url_keeps_v1_prefix_when_present() {
        // Regression: trimming the trailing `/v1` of opencode hosts
        // (https://opencode.ai/zen/go/v1) produced a 404 URL.
        assert_eq!(
            models_url("https://opencode.ai/zen/go/v1"),
            "https://opencode.ai/zen/go/v1/models"
        );
        assert_eq!(
            models_url("http://localhost:1234/v1"),
            "http://localhost:1234/v1/models"
        );
        assert_eq!(
            models_url("http://localhost:1234/"),
            "http://localhost:1234/v1/models"
        );
    }

    #[test]
    fn models_base_url_resolves_per_provider() {
        let cfg = Config::default();
        assert_eq!(
            models_base_url(&cfg, "opencode_go"),
            "https://opencode.ai/zen/go/v1"
        );
        assert_eq!(
            models_base_url(&cfg, "opencode_zen"),
            "https://opencode.ai/zen/v1"
        );
        assert_eq!(models_base_url(&cfg, "ollama"), "http://localhost:11434");
        // Unknown providers keep the legacy openai_compatible fallback.
        assert_eq!(
            models_base_url(&cfg, "openai"),
            cfg.openai_compatible.base_url
        );
    }
}
