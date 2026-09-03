# AGENTS.md Compliance — Fix Plan (Rust port)

**Date:** 2026-09-03
**Source:** docs/reviews/AGENTS_COMPLIANCE_REVIEW.md (module tracker)
**Repo:** /home/barontek/echo-ai-rust
**Scope:** the phased port of echo-ai-c. Each phase ships code + tests + (where the C version had them) ported regression tests + fault-injection tests for multi-step commit paths + verification evidence in docs/verification/.

## Conventions

- Item IDs: `P<n>` (phase) + letter (A = core, B = llm, C = tools, D = agent, E = server, F = tui, G = browser/frontend, R = rule/resolution). Mirrors the C repo's fix-plan convention.
- **Every bug port carries its regression test** from the C repo: the test must fail on the pre-fix C-equivalent behavior and pass on the new code (AGENTS.md "Verification discipline").
- Track progress by ticking the `[ ]` boxes. An item is DONE only when its tests are green under `cargo test`/nextest and, for unsafe/FFI paths, under the sanitizer/Miri stage with evidence recorded.
- Items marked `[defer]` are explicitly scoped out with a reason — never silently skipped.

## Phase 0 — Scaffolding

- [x] R0 config: `.conf` parser not ported — TOML/serde replaces it (user decision). C's config mid-list-cleanup gap (`E7`, no injection seam) is resolved-by-design; recorded in the review doc.
- [x] R1 workspace: Cargo workspace, 4 crates, workspace lint policy, release profile (overflow-checks + debug-assertions), deny.toml.
- [x] R2 toolchain: rust-toolchain.toml (stable 1.98.0 + components), flake.nix (stable + pinned nightly 2026-08-25, nextest/audit/deny/fuzz/llvm-cov, gcc, nodejs_22), flake.lock committed.
- [x] R3 CI: GitHub Actions — lint/test/sanitizers (ASan/UBSan/TSan stages)/miri/audit/backend-macos; rustup show recorded; macOS ASAN_OPTIONS=detect_leaks=0.
- [x] R4 scripts: debug-test.sh (exact/nocapture, gdb/lldb/miri/miri-gdb), lint.sh, check-file-lengths.sh.
- [x] R5 docs: AGENTS_COMPLIANCE_REVIEW.md (module tracker, known-gaps carry-forward) + this fix plan; docs/verification/ created.
- [x] R6 bin: main.rs arg parsing (--web default, --cli, --config, --debug, --help) with unit tests; --chat deliberately absent.
- [x] R7 AGENTS.md path amendment: "Repository layout" section documents that `src/...` references resolve to `crates/*/src/...`.

## Phase 1 — Core plane (config, utils, safety, session, change_tracker)

- [x] P1A config.rs: TOML config structs (serde, `Default` per section), `--config` loading (fail-fast on explicit missing path; defaults for absent default file), `config.toml.example`. Config loading wired into the bin.
- [x] P1B utils: string_utils, logging (JSON-lines, leveled, thread-safe), metrics (Prometheus text; updates to unknown names dropped silently — the C fault-injection property survives by construction), circuit_breaker (monotonic-clock state machine), rate_limiter (in-memory per-IP fixed window + rolling unlock throttle — SQLite persistence deliberately not ported, documented in module docs). `callbacks` deferred to Phase 4, `http_client` to Phase 3 (both land with their consumers).
- [ ] P1C html pipeline (7 modules): NOT STARTED — deferred to the next milestone (extractor design is a self-contained chunk; see tracker).
- [x] P1D safety.rs: workspace pinning (canonicalize-deepest + prefix check, symlink-escape tested), blocklists (configured-replaces-defaults semantics, C default lists verbatim), destructive-command screen, approval gating by mode, size cap.
- [x] P1E session: schema byte-compatible with C (`agent_sessions`, `provider_oauth`, `user_memory`, journal_mode=DELETE + synchronous=FULL, data dir 0700, salt/.pepper/.verifier 0600). Fernet exact format (0x80 | BE ts | IV | AES-128-CBC PKCS7 | HMAC-SHA256; scrypt N=2^18 r=8 p=1; key split 0..16 sign / 16..32 encrypt; future-timestamp rejection). Manager CRUD + list/purge/rename/events + OAuth store + memory (absent-vs-error distinction by type — C gap resolved-by-construction) + crash-safe password migration (marker/verifier.new/transactional re-encrypt/state-row recovery; interrupted-migration recovery tests both pre- and post-commit). Fault-injection: save-rollback test (abort trigger leaves committed row intact); migration crash-window tests.
- [x] P1F change_tracker: 64-slot undo/redo, redo-cleared-on-new-track, failed-restore rolls the undo stack back (fault-injection test).
- [ ] P1G fuzz targets: NOT STARTED — cargo-fuzz harnesses land with the next milestone alongside P1C (session_deserialize, fernet_token, html_extract).
- [x] P1H error conventions: thiserror `Error` enum in core (`error.rs`), anyhow available at boundaries, crate-level unwrap/expect deny outside tests with documented scoped allows (HMAC 16-byte-key invariant, mutex-poison fail-fast policy).

Notes:
- Known gaps re-baselined: `memory_get` absent-vs-error and session add-message rollback are resolved-by-construction (typed `Option`/transaction); `config` mid-list cleanup is moot (serde); `change_tracker` restore-rollback test added. `delegate` loop phase and `semantic_search` add-term rollback remain carried to Phase 3.
- Exceptions recorded: `hashbrown` 0.14/0.17 + `syn` 2/3 transitive duplicates (crate-root scoped allow + `cargo deny` at warn, see review doc); Miri runs with `-Zmiri-disable-isolation` and `--skip session::` (rusqlite is bundled C FFI; covered by sanitizer stages).

## Phase 2 — LLM providers

- [ ] P2A provider.rs trait (contract-only, mirrors provider.h) + factory + provider_models.
- [ ] P2B ollama.rs (chat, streaming, structured output, tool-call parsing) + ported tests + fuzz (ollama responses).
- [ ] P2C openai_compatible.rs (covers lmstudio/opencode_zen/opencode_go) + SSE parser + fuzz.
- [ ] P2D openai.rs (Codex, OAuth-only): request/stream/response + fuzz (Codex SSE, parse response, parse models).
- [ ] P2E oauth_*: codec (URL/PKCE/base64url), jwt (duplicate-key rejection, refresh-window arithmetic), vault (staging/clearing), http, device, callback (loopback:1455); mock-client tests ported from curl_stub pattern; fuzz (oauth jwt/token/callback).
- [ ] P2F fault-injection: single-flight token refresh path.

## Phase 3 — Tools

- [ ] P3A tool.rs (ToolResult) + registry.rs (registry_test cfg-gated wiring; documented structure exception).
- [ ] P3B file tools: read_file, write_file (+ change-tracker snapshot), edit (unique old_string, atomic rename), list_dir, glob_tool (workspace-bound), grep_tool (skip symlink/binary/out-of-workspace).
- [ ] P3C process tools: bash (process-group timeout), python_execute, git — libc signal handling behind cfg, macOS CI exercises both branches.
- [ ] P3D network tools: web_fetch (socket policy, size cap, HTML extraction, impersonate fallback), rest_api (socket rules), web_search + search providers (brave/tavily API, duckduckgo HTML scrape) + fuzz (duckduckgo html).
- [ ] P3E research tools: deep_search (port the double-free regression test — ownership discipline), semantic_search (TF-IDF; add_term rollback — carried gap), ingest_document.
- [ ] P3F misc tools: notes (name validation), memory (carried gap test), sqlite query/schema (read-only), ask_user, humanizer, tool_args (fuzz target).
- [ ] P3G delegate.rs: sub-agent loop; loop-phase commit fault-injection test (carried gap).
- [ ] P3H browser tools: tool_browser, tool_stealth_fetch (+ browser/ CDP driver + stealth in phase 7 per plan; tools registered with registry_test guard).

## Phase 4 — Agent

- [ ] P4A message.rs (Message/ToolCall/LLMResponse + serialization) + context.rs (trim by count/char budgets, smart_select, thinking split).
- [ ] P4B agent.rs + run loop (async, CancellationToken cancel) + prompt (cwd/time/memory/summary injection) + title (once per session, strip think tags) + summarize (skip oversized).
- [ ] P4C agent_tools.rs: tool execution with safety approval, result caps, failures recorded never abort.
- [ ] P4D ported regression tests: test_agent_save, test_agent_provider, test_context, test_message; callbacks dispatch.

## Phase 5 — Server

- [ ] P5A tls.rs: rcgen local CA + localhost cert, 0600 key files, PEM loading for custom certs, `[server] tls` config, regeneration on missing files.
- [ ] P5B middleware.rs: constant-time token compare (subtle), unlock gating (LOCKED/SETUP/UNLOCKED states), per-IP rate limit (SQLite buckets), CORS.
- [ ] P5C routes: all 16 C endpoints — status/health/config/setup/unlock/logout/change-password/sessions CRUD + import/export/debug-export/models/providers/chat/stream/metrics/undo/redo.
- [ ] P5D WS chat: protocol frames 1:1 (message/edit/regenerate/branch_switch/branch_info/approval_response/ask_user_response/stop; content/done/error/title_updated/tool_start/tool_end/approval_request/ask_user/session_start/history/branch_info/ready); per-connection agents; auth_generation invalidation on logout.
- [ ] P5E SSE: GET /api/stream with query-token auth; blocking POST /api/chat.
- [ ] P5F static serving: tower-http ServeDir (no symlink follow) + frontend dist; route-table parity test.
- [ ] P5G OAuth HTTP routes: status poll, start browser login, logout.

## Phase 6 — TUI

- [ ] P6A models first (all pure, terminal-independent): input (byte-based codepoint-atomic deletion, history), chat (wrap, block-append), keys (leader chords), command registry, stream classifier, markdown (subset CommonMark), tool_args, theme.
- [ ] P6B stores: model/prompt/session JSON-backed stores.
- [ ] P6C worker task + event ring (loom-tested) + shell (ratatui layout, poll loop).
- [ ] P6D dialogs (password/ask_user/approval/confirm-quit) + pickers + command palette + autocomplete.
- [ ] P6E port all test_tui_* suites; render layer stays thin over the models.

## Phase 7 — Browser, frontend, packaging

- [ ] P7A browser/ CDP driver: binary discovery (env → $BROWSER → PATH → macOS app bundles), spawn, NUL-framed JSON transport over pipes, id-matched responses with timeouts (port test_browser with fake_cdp pattern).
- [ ] P7B stealth.rs: launch flags, webdriver fingerprint overrides, Turnstile clicker; port test_stealth + fuzz (cdp_line, stealth_challenge).
- [ ] P7C frontend: vendor React source from ~/echo-ai-c/frontend (no node_modules), vite build in CI, dist served by P5F.
- [ ] P7D packaging: echo-ai.1 man page, deploy/ files adapted from C repo, README (Rust build, TLS trust instructions).

## Tracking

| Phase | Items | Status |
|---|---|---|
| 0 | R0-R7 | `[x]` all done |
| 1 | P1A-P1H | `[x]` done except P1C (html pipeline) and P1G (fuzz) — deferred to next milestone |
| 2 | P2A-P2F | pending |
| 3 | P3A-P3H | pending |
| 4 | P4A-P4D | pending |
| 5 | P5A-P5G | pending |
| 6 | P6A-P6E | pending |
| 7 | P7A-P7D | pending |

## Deferred (with reasons)

- `--chat` REPL, plugins subsystem — cut from scope by user decision (recorded in review doc).