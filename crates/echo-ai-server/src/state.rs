//! Shared server state: the runtime wiring shared by every request —
//! agent, registry, session store, safety, metrics, rate limiter, and
//! the unlock/auth state machine.
//!
//! Depends on: `echo-ai-core`, `tokio`, `subtle`.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use echo_ai_core::agent::run::{Agent, AgentConfig};
use echo_ai_core::change_tracker::ChangeTracker;
use echo_ai_core::config::Config;
use echo_ai_core::llm::factory;
use echo_ai_core::llm::http::{HttpClient, ReqwestClient};
use echo_ai_core::safety::SafetyConfig;
use echo_ai_core::session::SessionManager;
use echo_ai_core::tools::registry::Registry;
use echo_ai_core::tools::search::SearchProvider;
use echo_ai_core::tools::semantic::SemanticIndex;
use echo_ai_core::utils::metrics::Metrics;
use echo_ai_core::utils::rate_limiter::RateLimiter;
use serde::Deserialize;
use subtle::ConstantTimeEq;

/// Server lifecycle state.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ServerState {
    /// No vault exists yet (first run).
    Setup,
    /// Vault exists but is locked.
    Locked,
    /// Unlocked; requests carry a valid token.
    Unlocked,
}

/// Unlock token + generation (generation bumps on logout, invalidating
/// every outstanding token).
#[derive(Debug)]
pub struct AuthState {
    /// Current state.
    pub state: ServerState,
    /// Current unlock token (constant-time compared).
    pub token: Option<String>,
    /// Bumped on every logout.
    pub generation: u64,
}

impl Default for AuthState {
    fn default() -> Self {
        Self {
            state: ServerState::Setup,
            token: None,
            generation: 0,
        }
    }
}

/// Shared application state.
pub struct AppState {
    /// The loaded configuration.
    pub config: Config,
    /// Effective safety policy.
    pub safety: Arc<SafetyConfig>,
    /// The shared agent (serialized by the WS task; REST turns await it
    /// through the turn lock).
    pub agent: Arc<Agent>,
    /// Tool registry.
    pub registry: Arc<Registry>,
    /// Session store slot (absent when `session.enabled` is false; a
    /// browser-driven setup fills it after startup).
    pub session: Arc<Mutex<Option<Arc<SessionManager>>>>,
    /// Change tracker for undo/redo.
    pub tracker: Arc<Mutex<ChangeTracker>>,
    /// Metrics registry.
    pub metrics: Metrics,
    /// Per-IP rate limiter.
    pub rate_limiter: RateLimiter,
    /// Auth state machine.
    pub auth: Mutex<AuthState>,
    /// HTTP client.
    pub http: Arc<dyn HttpClient>,
    /// Semantic search index.
    pub index: Arc<SemanticIndex>,
    /// Serializes shared-agent turns.
    pub turn_lock: tokio::sync::Mutex<()>,
    /// Data directory (session vault / TLS).
    pub data_dir: std::path::PathBuf,
    /// Server settings.
    pub server: echo_ai_core::config::Server,
}

impl AppState {
    /// Builds the shared state from config + wiring.
    ///
    /// # Errors
    /// `Error::Config` when the configured provider cannot be built.
    /// # Panics
    /// Only if the session slot lock is poisoned (fail fast).
    #[allow(clippy::expect_used)] // poisoned slot = invariant violation
    pub fn build(
        config: Config,
        session: Option<Arc<SessionManager>>,
        data_dir: std::path::PathBuf,
    ) -> Result<Arc<Self>, echo_ai_core::error::Error> {
        let safety = Arc::new(SafetyConfig::from_config(&config.safety, None));
        let http: Arc<dyn HttpClient> = Arc::new(ReqwestClient::new());
        let index = Arc::new(SemanticIndex::new());
        let search = SearchProvider::from_config(&config).map(Arc::new);
        let browser = Arc::new(echo_ai_core::browser::BrowserManager::new());
        let registry = Arc::new(Registry::build(
            &config,
            search,
            index.clone(),
            Arc::clone(&browser),
        ));
        let tracker = Arc::new(Mutex::new(ChangeTracker::new()));

        let session_slot: Arc<Mutex<Option<Arc<SessionManager>>>> = Arc::new(Mutex::new(session));
        #[allow(clippy::expect_used)] // poisoned slot = invariant violation
        let codex_token = session_slot
            .lock()
            .expect("session slot lock poisoned")
            .as_ref()
            .and_then(|sm| sm.oauth_get("openai").ok().flatten());
        let provider = factory::create_provider(&config, Some(http.clone()), codex_token)?;

        let agent_config = AgentConfig::from(&config);
        let agent = Arc::new(Agent {
            provider,
            registry: registry.clone(),
            config: agent_config,
            safety: safety.clone(),
            app_config: config.clone(),
            session: session_slot.clone(),
            tracker: Some(tracker.clone()),
            ask_user: None,
            http: http.clone(),
        });

        let auth = if !config.session.enabled {
            // Persistence disabled: the server is always unlocked.
            AuthState {
                state: ServerState::Unlocked,
                token: Some(random_token()),
                generation: 0,
            }
        } else if session_slot
            .lock()
            .expect("session slot lock poisoned")
            .is_some()
        {
            // Vault exists: locked until the password is verified.
            AuthState::default()
        } else {
            // Vault will be created by the web UI's setup screen.
            AuthState {
                state: ServerState::Setup,
                token: None,
                generation: 0,
            }
        };

        let server = config.server.clone();

        Ok(Arc::new(Self {
            config,
            safety,
            agent,
            registry,
            session: session_slot.clone(),
            tracker,
            metrics: Metrics::new(),
            rate_limiter: RateLimiter::default(),
            auth: Mutex::new(auth),
            http,
            index,
            turn_lock: tokio::sync::Mutex::new(()),
            data_dir,
            server,
        }))
    }

    /// Issues a fresh unlock token (constant-time comparable later).
    ///
    /// # Panics
    /// Only if the auth lock is poisoned (a panic while another thread
    /// held it) — fail fast, an inconsistent auth state must not be
    /// silently continued.
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    pub fn unlock(&self) -> String {
        let token = random_token();
        let mut auth = self.auth.lock().expect("auth lock poisoned");
        auth.token = Some(token.clone());
        auth.state = ServerState::Unlocked;
        auth.generation += 1;
        token
    }

    /// Validates a token (constant-time).
    ///
    /// # Panics
    /// Same poisoned-lock policy as [`Self::unlock`].
    #[must_use]
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    pub fn validate_token(&self, token: &str) -> bool {
        let auth = self.auth.lock().expect("auth lock poisoned");
        match &auth.token {
            Some(expected) => token.as_bytes().ct_eq(expected.as_bytes()).into(),
            None => false,
        }
    }

    /// Whether the server needs setup (no vault yet).
    ///
    /// # Panics
    /// Same poisoned-lock policy as [`Self::unlock`].
    #[must_use]
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    pub fn needs_setup(&self) -> bool {
        self.auth.lock().expect("auth lock poisoned").state == ServerState::Setup
    }

    /// Marks setup complete (state -> Locked; the caller creates the
    /// session manager and stores it elsewhere).
    ///
    /// # Panics
    /// Same poisoned-lock policy as [`Self::unlock`].
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    pub fn mark_setup_done(&self) {
        let mut auth = self.auth.lock().expect("auth lock poisoned");
        auth.state = ServerState::Locked;
        auth.token = None;
    }

    /// Logs out (bump generation, drop token).
    ///
    /// # Panics
    /// Same poisoned-lock policy as [`Self::unlock`].
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    pub fn logout(&self) {
        let mut auth = self.auth.lock().expect("auth lock poisoned");
        auth.token = None;
        auth.state = ServerState::Locked;
        auth.generation += 1;
    }
}

/// Axum provides `State<Arc<AppState>>` extraction natively (no custom
/// extractor needed).
///
/// Random 32-hex-char token.
fn random_token() -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut bytes = [0u8; 16];
    rand::RngCore::fill_bytes(&mut rand::thread_rng(), &mut bytes);
    let mut out = String::with_capacity(32);
    for b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
    }
    out
}

/// Generation counter exposed for WS auth checks.
#[derive(Debug, Default)]
pub struct AuthGeneration(pub AtomicU64);

impl AuthGeneration {
    /// Reads the current generation.
    #[must_use]
    pub fn get(&self) -> u64 {
        self.0.load(Ordering::Relaxed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tokens_are_random_and_unique() {
        let a = random_token();
        let b = random_token();
        assert_eq!(a.len(), 32);
        assert_ne!(a, b);
    }

    #[test]
    fn unlock_validate_logout_cycle() {
        let config = Config::default();
        let state = AppState::build(config, None, std::path::PathBuf::from("/tmp")).expect("build");
        assert!(!state.needs_setup(), "no-session servers start unlocked");
        let token = state.unlock();
        assert!(state.validate_token(&token));
        assert!(!state.validate_token("wrong"));
        state.logout();
        assert!(!state.validate_token(&token));
    }
}
