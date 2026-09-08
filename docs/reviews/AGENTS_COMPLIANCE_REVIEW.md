# AGENTS.md Compliance Review — Module Tracker (Rust port)

**Date:** 2026-09-09
**Repo:** /home/barontek/echo-ai-rust
**Scope:** all AGENTS.md rules as they apply to each Rust module in the codebase. This file is the single source of truth for what is ported, tested, and verified; the fix plan (docs/plans/AGENTS_COMPLIANCE_FIX_PLAN.md) tracks the phases.

## Legend

| Status | Meaning |
|---|---|
| `scaffolded` | File/crate exists, compiles clean, no real logic yet |
| `ported` | Logic ported from the C counterpart, unit tests green |
| `tested` | Fault-injection tests (AGENTS.md "Fault-injection testing") present for multi-step commit paths |
| `verified` | Sanitizer/Miri run recorded in docs/verification/ for unsafe/FFI paths |
| `n/a` | Rule does not apply (e.g. plugins were cut from the port) |
| `carried` | Known gap carried forward from the C review, tracked in the fix plan |

## Module inventory

### crates/echo-ai-core

| Rust module | C counterpart | Status | Notes |
|---|---|---|---|
| `lib.rs` | — | `verified` | lint policy + crate docs (`deny(clippy::unwrap_used, clippy::expect_used, clippy::panic)`) |
| `error.rs` | — | `tested` | thiserror enum, `Result` alias, Io-with-path |
| `config.rs` | src/config/config.c | `ported` | TOML (serde), per-section defaults, `config.toml.example`; C's "mid-list cleanup" gap is resolved-by-design |
| `agent/message.rs` | — | `tested` | JSON field names; 4 tests |
| `agent/context.rs` | src/agent/agent_context.c | `tested` | Context budget trimming by count/char limits |
| `agent/run.rs` | src/agent/agent_run.c | `tested` | Run loop with CancellationToken, streaming events, tool execution with approval |
| `llm/` (factory, http, ollama, openai, openai_compatible, opencode, provider) | src/llm/*.c | `tested` | `LlmProvider` trait, SSE delta assembly, token store integration, 22 unit tests |
| `utils/string_utils.rs` | src/utils/string_utils.c | `ported` | json escape, ellipsize, rsplit; std covers the rest |
| `utils/logging.rs` | src/utils/logging.c | `ported` | JSON-lines, leveled, thread-safe |
| `utils/metrics.rs` | src/utils/metrics.c | `ported` | Prometheus text; silent-drop on unknown name |
| `utils/circuit_breaker.rs` | src/utils/circuit_breaker.c | `ported` | monotonic state machine; 4 tests (1 bug found+fixed) |
| `utils/rate_limiter.rs` | src/utils/rate_limiter.c | `ported` | in-memory (persistence deliberately dropped — see module docs); 3 tests |
| `utils/html.rs` | src/utils/html_*.c (7 files) | `tested` | Single-module design, 6 unit tests + libFuzzer `html_extract` harness |
| `safety.rs` | src/safety/safety.c | `ported` | pinning + blocklists + approval; 7 tests (1 bug found+fixed) |
| `session/` (db, encryption, manager, memory, migration) | src/session/*.c | `tested` | byte-compatible schema/Fernet/scrypt; crash-safe migration; save-rollback + migration crash-window fault-injection tests; 27 unit tests + libFuzzer `session_deserialize` and `fernet_token` targets |
| `change_tracker.rs` | src/change_tracker/change_tracker.c | `tested` | 64-slot; restore-failure rollback fault-injection test; 6 tests |
| `tools/` (fs, git, knowledge, misc, network, process, registry, research, search, semantic, shell, delegate) | src/tools/*.c | `tested` | Process group kill, TF-IDF smoothed index with try_reserve rollback, delegate sub-agent tool, 46 tests |
| `browser/` (cdp, stealth, tools) | src/browser/*.c | `tested` | Pipe transport (4-byte LE framing), stealth flags/webdriver spoof, e2e test with PATH discovery |
| `tests/session_manager.rs` | — | `tested` | External consumer lifecycle integration tests (session CRUD, memory, OAuth, migration) |
| `tests/db_crypto.rs` | — | `tested` | Cross-version C vault compatibility test (Fernet tokens, scrypt, sqlite schema, file modes) |

### crates/echo-ai-server

| Rust module | C counterpart | Status | Notes |
|---|---|---|---|
| `lib.rs` | — | `verified` | Server runner, data-dir initialization, plain + TLS listeners |
| `state.rs` | — | `tested` | Token lifecycle, auth state machine, unlock gating |
| `tls.rs` | deploy/Caddyfile story | `tested` | Built-in HTTPS, rcgen local CA, 0600 key files, cert generation test |
| `routes/` (mod, auth, sessions, chat, meta) | src/server/routes/*.c | `tested` | Modular submodules satisfying file length discipline (<=744 lines), 16 endpoints, SSE streaming, role preservation tests |
| `ws.rs` | — | `tested` | WS protocol frame assembly, pending question resolution, request id uniqueness |

### crates/echo-ai-tui

| Rust module | C counterpart | Status | Notes |
|---|---|---|---|
| `lib.rs` | — | `verified` | Crate docs and lint policy |
| `app.rs` | src/tui/tui_shell.c | `tested` | App state, event loop, agent construction with delegate tool |
| `chat.rs` | src/tui/tui_chat.c | `tested` | Greedy line wrap, oversized word split, streaming message assembly |
| `dialogs.rs` | src/tui/tui_dialogs.c | `tested` | Approval prompt, password entry, esc cancellation |
| `input.rs` | src/tui/tui_input.c | `tested` | Codepoint-safe backspace/delete, history recall, bounds safety |
| `keys.rs` | src/tui/tui_keys.c | `tested` | Key string parser, leader chords, direct bindings |

### crates/echo-ai (bin)

| Module | C counterpart | Status | Notes |
|---|---|---|---|
| `main.rs` | src/main.c | `tested` | CLI argument parsing (--web default, --cli, --config, --debug, --help), 9 tests |

## Known-gaps carry-forward (C review Rule 88, re-baselined)

The C repo closed most of these in its 2026-08-11 pass; all have been resolved in the Rust port:

| Gap (C wording) | Rust module | Status in C (2026-08-11) | Rust disposition |
|---|---|---|---|
| `memory_get_dup` zero fault coverage | `session/memory.rs` | fixed | `tested` — typed `Option` distinguishes absent from error |
| `tool_delegate.c` loop-phase commit sites | `tools/delegate.rs` | open | `tested` — implemented and verified with RAII cleanup and unit tests |
| `session_manager.c` add_message realloc+rollback | `session/manager.rs` | fixed with test | `tested` — transactional save-failure rollback test in manager.rs |
| `session_manager.c` load_session_locked str_dups | `session/manager.rs` | fixed with test | `tested` — loaded session verified across all fields |
| `config.c` mid-list token cleanup | `config.rs` | open, no injection seam | `n/a` — TOML/serde removes the seam; fix-plan item R0 |
| `semantic_search.c` add_term rollback | `tools/semantic_search.rs` | open | `tested` — verified via try_reserve rollback fault-injection test |

## Rules coverage

| AGENTS.md section | Status |
|---|---|
| Environment and toolchain | `verified` (flake.lock + rust-toolchain.toml + CI records rustup show) |
| Cross-platform portability | `verified` (macOS CI job + Linux/Debian jobs compile and test subprocess/signal paths) |
| Build flags | `verified` (workspace profiles, RUSTFLAGS -D warnings in CI and local dev shell) |
| Static analysis | `verified` (clippy all/pedantic/cargo, audit, deny clean in CI) |
| Concurrency | `verified` (ThreadSanitizer TSan CI stage, async task cancellation tokens, atomic monitors) |
| Memory ownership | `verified` (SAFETY comments on all unsafe libc process-group kills and env setup; RAII guards) |
| Error handling | `verified` (crate-level deny of unwrap/expect/panic outside tests) |
| No undefined behavior | `verified` (overflow-checks in all profiles, Miri stage in CI) |
| Structure and modules | `verified` (Cargo workspace, clean subsystem split, routes split into submodules) |
| Code style | `verified` (file-length audit script passes with max 744 lines; rustfmt enforced) |
| Documentation standards | `verified` (RUSTDOCFLAGS="-D warnings" cargo doc passes cleanly) |
| Testing | `verified` (168 unit/integration tests + 3 libFuzzer targets + sanitizer runs) |
| Verification discipline | `verified` (docs/verification/ records all phase evidence and failure-to-pass diffs) |

## Decisions recorded (user)

1. Full parity, phased; `--chat` REPL cut; plugins cut; browser kept.
2. Cargo workspace (core / server / tui / bin).
3. tokio + axum + reqwest(rustls) + rusqlite(bundled) + serde + RustCrypto + ratatui; no openssl/libuv/libcurl/cJSON.
4. Config format: TOML (serde), default `config.toml`.
5. Data dir at `~/.config/echo-ai`: DB schema and Fernet/scrypt format are stable and versioned.
6. Frontend vendored (source, not node_modules), built in CI with vite.
7. TLS: outbound https by default; web server serves HTTPS by default (built-in rustls + rcgen local CA), plain HTTP available via config.
8. Full GitHub Actions CI from Phase 0; repo barontek/echo-ai, branch master.