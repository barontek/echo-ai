//! The tool registry: built-in tools wired with config-derived state,
//! enablement filtering, and provider-facing specs.
//!
//! The C version's `REGISTRY_TEST` seam (skip wiring the full registry
//! for tests) is unnecessary in Rust — every tool is a plain struct in
//! the same crate, so there is no link-time cost to building them all;
//! the seam is resolved-by-design (recorded in the review doc).
//!
//! Depends on: crate `config`, `llm::provider`, `tools::{fs,git,knowledge,
//! misc,network,research,search,semantic,shell,tool}`.

use std::collections::HashMap;
use std::sync::Arc;

use serde_json::Value;

use crate::config::Config;
use crate::llm::provider::ToolSpec;

use super::fs::{Edit, Glob, Grep, ListDir, ReadFile, WriteFile};
use super::git::Git;
use super::knowledge::{Memory, Notes, SqliteQuery, SqliteSchema};
use super::misc::{AskUser, Humanizer};
use super::network::{RestApi, WebFetch};
use super::research::DeepSearch;
use super::search::{SearchProvider, WebSearch};
use super::semantic::{IngestDocument, SemanticIndex, SemanticSearch};
use super::shell::{Bash, PythonExecute};
use super::tool::Tool;

/// The process-wide tool table.
#[derive(Default)]
pub struct Registry {
    tools: HashMap<String, Arc<dyn Tool>>,
}

impl Registry {
    /// Builds the registry from config and shared state.
    ///
    /// * `cfg` — for tool enablement and search provider config.
    /// * `search` — the configured web search backend.
    /// * `index` — the shared semantic-search index.
    ///
    /// The session store and change tracker are NOT held here: tools
    /// receive them per-execution through the `ToolContext`, so one
    /// registry serves both the server and the TUI.
    pub fn build(
        cfg: &Config,
        search: Option<Arc<SearchProvider>>,
        index: Arc<SemanticIndex>,
    ) -> Self {
        let mut registry = Self::default();

        let mut register = |tool: Arc<dyn Tool>| {
            let name = String::from(tool.name());
            registry.tools.insert(name, tool);
        };

        register(Arc::new(ReadFile));
        register(Arc::new(WriteFile));
        register(Arc::new(Edit));
        register(Arc::new(ListDir));
        register(Arc::new(Glob));
        register(Arc::new(Grep));
        register(Arc::new(Bash));
        register(Arc::new(PythonExecute));
        register(Arc::new(Git));
        register(Arc::new(WebFetch));
        register(Arc::new(RestApi));
        register(Arc::new(Humanizer));
        register(Arc::new(AskUser));
        register(Arc::new(Notes));
        register(Arc::new(SqliteSchema));
        register(Arc::new(SqliteQuery));

        if let Some(search) = search {
            register(Arc::new(WebSearch::new(search.clone())));
            register(Arc::new(DeepSearch::new(search)));
        }

        // Session-backed tools are always registered; they error cleanly
        // at execution when persistence is disabled (the C version's
        // registry wiring, minus the link-time gymnastics).
        register(Arc::new(Memory));
        register(Arc::new(SemanticSearch::new(index.clone())));
        register(Arc::new(IngestDocument::new(index)));

        // Enablement filtering.
        if !cfg.tools.enabled.is_empty() {
            let allowed: std::collections::HashSet<String> =
                cfg.tools.enabled.iter().cloned().collect();
            registry.tools.retain(|name, _| allowed.contains(name));
        }

        registry
    }

    /// Looks up a tool by name.
    #[must_use]
    pub fn get(&self, name: &str) -> Option<Arc<dyn Tool>> {
        self.tools.get(name).cloned()
    }

    /// All registered tool names (sorted).
    #[must_use]
    pub fn names(&self) -> Vec<String> {
        let mut names: Vec<String> = self.tools.keys().cloned().collect();
        names.sort();
        names
    }

    /// Provider-facing tool specs for the model.
    #[must_use]
    pub fn specs(&self) -> Vec<ToolSpec> {
        self.tools
            .values()
            .map(|t| ToolSpec {
                name: String::from(t.name()),
                description: String::from(t.description()),
                parameters: t.parameters(),
            })
            .collect()
    }

    /// Number of registered tools.
    #[must_use]
    pub fn len(&self) -> usize {
        self.tools.len()
    }

    /// Whether the registry is empty.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.tools.is_empty()
    }
}

/// Convenience: an empty context value used by tests.
#[allow(unused)]
fn _unused(_: Value) {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_all_default_tools() {
        let registry = Registry::build(&Config::default(), None, Arc::new(SemanticIndex::new()));
        let names = registry.names();
        for expected in [
            "read_file",
            "write_file",
            "edit",
            "list_dir",
            "glob",
            "grep",
            "bash",
            "python_execute",
            "git",
            "web_fetch",
            "rest_api",
            "humanizer",
            "ask_user",
            "notes",
            "sqlite_schema",
            "sqlite_query",
            "memory",
            "semantic_search",
            "ingest_document",
        ] {
            assert!(
                names.contains(&String::from(expected)),
                "missing {expected}"
            );
        }
        // Specs are well-formed for the providers.
        for spec in registry.specs() {
            assert!(!spec.name.is_empty());
            assert!(!spec.description.is_empty());
            assert!(spec.parameters.is_object());
        }
    }

    #[test]
    fn enablement_filter_applies() {
        let mut cfg = Config::default();
        cfg.tools.enabled = vec![String::from("read_file"), String::from("bash")];
        let registry = Registry::build(&cfg, None, Arc::new(SemanticIndex::new()));
        assert_eq!(registry.len(), 2);
        assert!(registry.get("read_file").is_some());
        assert!(registry.get("write_file").is_none());
    }

    #[test]
    fn search_tools_register_with_provider() {
        let mut cfg = Config::default();
        cfg.search.provider = String::from("duckduckgo");
        let provider = Arc::new(SearchProvider::from_config(&cfg).expect("provider"));
        let registry = Registry::build(&cfg, Some(provider), Arc::new(SemanticIndex::new()));
        assert!(registry.get("web_search").is_some());
        assert!(registry.get("deep_search").is_some());
    }

    #[test]
    fn unknown_tool_lookup_returns_none() {
        let registry = Registry::build(&Config::default(), None, Arc::new(SemanticIndex::new()));
        assert!(registry.get("no_such_tool").is_none());
    }
}
