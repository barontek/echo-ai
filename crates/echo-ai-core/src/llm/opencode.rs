//! `OpenCode Zen` and `OpenCode Go` providers: thin wrappers that point the
//! `OpenAI`-compatible client at the `OpenCode` endpoints with the shared
//! `opencode` bearer token.
//!
//! Depends on: crate `llm::{http, openai_compatible, provider}`.

use futures_util::future::BoxFuture;
use std::sync::Arc;

use super::http::HttpClient;
use super::openai_compatible::OpenAiCompatible;
use super::provider::{ChatRequest, ChatResponse, LlmError, LlmProvider, StreamEvent};

macro_rules! opencode_provider {
    ($name:ident, $catalog:literal, $doc:literal) => {
        #[doc = $doc]
        #[derive(Clone)]
        pub struct $name {
            inner: OpenAiCompatible,
        }

        impl $name {
            /// Creates the provider against `base_url` with the shared
            /// `OpenCode` bearer token.
            pub fn new(base_url: String, token: String, http: Arc<dyn HttpClient>) -> Self {
                Self {
                    inner: OpenAiCompatible::new(base_url, Some(token), http),
                }
            }
        }

        impl LlmProvider for $name {
            fn name(&self) -> &'static str {
                $catalog
            }

            fn chat(
                self: std::sync::Arc<Self>,
                req: &ChatRequest,
            ) -> BoxFuture<'static, Result<ChatResponse, LlmError>> {
                let inner = std::sync::Arc::new(self.inner.clone());
                let req = req.clone();
                Box::pin(async move { inner.chat(&req).await })
            }

            fn chat_stream(
                self: std::sync::Arc<Self>,
                req: &ChatRequest,
            ) -> BoxFuture<'static, Result<tokio::sync::mpsc::Receiver<StreamEvent>, LlmError>>
            {
                let inner = std::sync::Arc::new(self.inner.clone());
                let req = req.clone();
                Box::pin(async move { inner.chat_stream(&req).await })
            }

            fn supports_effort(&self) -> bool {
                true
            }
        }
    };
}

opencode_provider!(
    OpenCodeZen,
    "opencode_zen",
    "`OpenCode Zen` provider (`OpenAI`-compatible protocol)."
);

opencode_provider!(
    OpenCodeGo,
    "opencode_go",
    "`OpenCode Go` provider (`OpenAI`-compatible protocol)."
);

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn catalog_names() {
        let http: Arc<dyn HttpClient> = Arc::new(super::super::http::ReqwestClient::new());
        let zen = OpenCodeZen::new(
            String::from("https://opencode.ai/zen/v1"),
            String::from("t"),
            http.clone(),
        );
        let go = OpenCodeGo::new(
            String::from("https://opencode.ai/zen/go/v1"),
            String::from("t"),
            http,
        );
        assert_eq!(zen.name(), "opencode_zen");
        assert_eq!(go.name(), "opencode_go");
        assert!(zen.supports_effort());
    }
}
