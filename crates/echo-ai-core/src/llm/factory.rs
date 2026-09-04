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
    let base = base_url.trim_end_matches('/').trim_end_matches("/v1");
    let headers: Vec<(&str, &str)> = token
        .map(|t| vec![("Authorization", t)])
        .unwrap_or_default();
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
            let url = format!("{base}/models");
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
}
