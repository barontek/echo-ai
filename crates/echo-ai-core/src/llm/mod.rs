//! LLM provider layer: the `LlmProvider` trait (contract-only, mirroring
//! the provider contract), the HTTP plumbing, and the concrete
//! providers.
//!
//! Providers: `ollama`, `openai_compatible` (LM Studio, vLLM,
//! llama.cpp), `opencode_zen`, `opencode_go`, and `openai` (Codex).
//! Streaming is delivered as a line-oriented channel (see `http`), so
//! every parser is a pure function over lines — unit-testable without a
//! network.
//!
//! Depends on: `reqwest`, `serde_json`, `tokio`, crate `agent::message`.

pub mod factory;
pub mod http;
pub mod ollama;
pub mod openai;
pub mod openai_compatible;
pub mod opencode;
pub mod provider;
