# echo-ai-core

The engine behind the web server and TUI: agent loop, LLM providers,
tool registry, session store (SQLite + Fernet encryption), safety
enforcement, config, and shared utilities.

Module layout mirrors the responsibilities: agent, LLM providers,
tool registry, session store, safety, config, utilities. Depends on `serde`/`serde_json`, `rusqlite` (bundled),
`reqwest` (rustls), `RustCrypto` crates, `tokio`.

## Module map

| Module | Responsibility |
|---|---|
| `config` | `TOML` config (serde) |
| `safety` | workspace pinning, path/URL/command/socket checks, approval gating |
| `session` | SQLite schema, Fernet encryption (scrypt salt‖pepper), manager, branches, memory, migration |
| `agent` | run loop (async, cancellable), prompt/title/summarize, context windowing |
| `llm` | `LlmProvider` trait + ollama / openai (Codex OAuth) / openai_compatible / opencode_zen providers |
| `tools` | `Tool` trait + registry + ~39 built-in tools |
| `change_tracker` | file undo/redo stacks |
| `utils` | logging, metrics, circuit breaker, rate limiter, callbacks, html pipeline, strings |
| `browser` | CDP driver + stealth over tokio process pipes |

## Testing

Unit tests inline (`#[cfg(test)] mod tests`), integration tests in
`tests/` (`session_manager.rs`, `db_crypto.rs`, ...), fuzz targets via
`cargo fuzz` for external-input parsers (config-free: session blobs,
fernet tokens, tool args, SSE streams, html). Fault-injection tests for
multi-step commit paths per AGENTS.md.