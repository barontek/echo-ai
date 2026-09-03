# AGENTS.md Compliance Review — Module Tracker (Rust port)

**Date:** 2026-09-03
**Repo:** /home/barontek/echo-ai-rust (port of /home/barontek/echo-ai-c at ~2026-08-11 HEAD)
**Scope:** all AGENTS.md rules as they apply to each Rust module as it is ported. This file is the single source of truth for what is ported, tested, and verified; the fix plan (docs/plans/AGENTS_COMPLIANCE_FIX_PLAN.md) drives the work.

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
| `lib.rs` | — | `scaffolded` | lint policy + crate docs |
| `error.rs` | — | `tested` | thiserror enum, `Result` alias, Io-with-path |
| `config.rs` | src/config/config.c | `ported` | TOML (serde), per-section defaults, `config.toml.example`; C's "mid-list cleanup" gap is resolved-by-design (fix plan R0) |
| `agent/message.rs` | src/agent/message.c | `ported` | C-compatible JSON field names; 4 tests |
| `utils/string_utils.rs` | src/utils/string_utils.c | `ported` | json escape, ellipsize, rsplit; std covers the rest |
| `utils/logging.rs` | src/utils/logging.c | `ported` | JSON-lines, leveled, thread-safe |
| `utils/metrics.rs` | src/utils/metrics.c | `ported` | Prometheus text; silent-drop on unknown name (C fault tests ported in spirit) |
| `utils/circuit_breaker.rs` | src/utils/circuit_breaker.c | `ported` | monotonic state machine; 4 tests (1 bug found+fixed) |
| `utils/rate_limiter.rs` | src/utils/rate_limiter.c | `ported` | in-memory (persistence deliberately dropped — see module docs); 3 tests |
| `utils/callbacks.rs` | src/utils/callbacks.c | pending | Phase 4 (with agent) |
| `utils/http_client.rs` | src/utils/http_client.c | pending | Phase 3 (with network tools) |
| `safety.rs` | src/safety/safety.c | `ported` | pinning + blocklists + approval; 7 tests (1 bug found+fixed) |
| `session/` (db, encryption, manager, memory, migration) | src/session/*.c | `tested` | byte-compatible schema/Fernet/scrypt; crash-safe migration; 27 tests; save-rollback + migration crash-window fault-injection tests |
| `change_tracker.rs` | src/change_tracker/change_tracker.c | `tested` | 64-slot; restore-failure rollback fault-injection test; 5 tests |
| `utils/html_*.rs` | src/utils/html_*.c (7 files) | pending | deferred to next milestone (P1C) |
| `agent/` (run, prompt, title, summarize, context) | src/agent/*.c | pending | Phase 4 |
| `llm/` | src/llm/*.c | pending | Phase 2 |
| `tools/` | src/tools/*.c | pending | Phase 3 |
| `browser/` | src/browser/*.c | pending | Phase 7 |

### crates/echo-ai-server

| Rust module | C counterpart | Status | Notes |
|---|---|---|---|
| `lib.rs` | — | `scaffolded` | |
| `server.rs` | src/server/server.c | pending | axum; libuv/http_parse/websocket replaced upstream (fuzz targets dropped with them) |
| `tls.rs` | deploy/Caddyfile story | pending | built-in HTTPS (user decision); rcgen local CA, 0600 key files |
| `routes/*.rs` | src/server/routes/*.c | pending | 16 endpoints, SSE, WS protocol frames 1:1 |
| `middleware.rs` | src/server/middleware.c | pending | constant-time token compare (subtle), unlock gating, CORS |

### crates/echo-ai-tui

| Rust module | C counterpart | Status | Notes |
|---|---|---|---|
| `lib.rs` | — | `scaffolded` | |
| `tui_*.rs` (shell, worker, events, chat, input, keys, command, cmd, dialogs, picker, render, stream, theme, autocomplete, stores, markdown, tool_args) | src/tui/*.c | pending | ratatui + crossterm; models stay terminal-independent |

### crates/echo-ai (bin)

| Module | C counterpart | Status | Notes |
|---|---|---|---|
| `main.rs` | src/main.c | `ported` (scaffold) | arg parsing + tests; `--chat` REPL not ported (user decision); plugins not ported (user decision) |

## Known-gaps carry-forward (C review Rule 88, re-baselined)

The C repo closed most of these in its 2026-08-11 pass; each carries its current truth:

| Gap (C wording) | Rust module | Status in C (2026-08-11) | Rust disposition |
|---|---|---|---|
| `memory_get_dup` zero fault coverage | `session/memory.rs` | still open (E8 deferred) | `carried` → fault-injection test |
| `tool_delegate.c` loop-phase commit sites | `tools/delegate.rs` | still open (E9 partial) | `carried` → fault-injection test |
| `session_manager.c` add_message realloc+rollback | `session/manager.rs` | fixed with test | port the regression test |
| `session_manager.c` load_session_locked str_dups | `session/manager.rs` | fixed with test | port the regression test |
| `config.c` mid-list token cleanup | `config.rs` | open, no injection seam | `n/a` — TOML/serde removes the seam; fix-plan item R0 |
| `semantic_search.c` add_term rollback | `tools/semantic_search.rs` | open | `carried` → fault-injection test via try_reserve |

## Rules coverage

| AGENTS.md section | Status |
|---|---|
| Environment and toolchain | `verified` (flake.lock + rust-toolchain.toml + CI records rustup show) |
| Cross-platform portability | in progress — macOS CI job exists; subprocess modules land Phase 3+ |
| Build flags | `verified` (workspace profiles, RUSTFLAGS -D warnings in CI) |
| Static analysis | `verified` (clippy all/pedantic/cargo, audit, deny in CI) |
| Concurrency | in progress — loom tests planned for session manager, change tracker, event ring |
| Memory ownership | in progress — SAFETY comments on all unsafe (libc in process/git/python_execute/server/web_fetch) |
| Error handling | `verified` (crate-level deny of unwrap/expect outside tests) |
| No undefined behavior | in progress — overflow-checks everywhere, Miri stage in CI |
| Structure and modules | `verified` (workspace mirrors C module boundaries) |
| Code style | in progress — file-length audit script |
| Documentation standards | in progress — missing_docs warn + doc -D warnings in CI |
| Testing | in progress — nextest; fault-injection pattern in AGENTS.md |
| Verification discipline | in progress — docs/verification/ archive policy |

## Decisions recorded (user)

1. Full parity, phased; `--chat` REPL cut; plugins cut; browser kept.
2. Cargo workspace (core / server / tui / bin).
3. tokio + axum + reqwest(rustls) + rusqlite(bundled) + serde + RustCrypto + ratatui; no openssl/libuv/libcurl/cJSON.
4. Config format: TOML (serde), default `config.toml`.
5. Data dir compatible with the C version (`~/.config/echo-ai`): same DB schema, same Fernet/scrypt format.
6. Frontend vendored (source, not node_modules), built in CI with vite.
7. TLS: outbound https by default; web server serves HTTPS by default (built-in rustls + rcgen local CA), plain HTTP available via config.
8. Full GitHub Actions CI from Phase 0; repo barontek/echo-ai-rust, branch master.