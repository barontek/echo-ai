# Phase 2–7 verification evidence

**Date:** 2026-09-04
**Repo:** /home/barontek/echo-ai-rust
**Scope:** LLM providers (Phase 2), tools (Phase 3), agent loop (Phase 4),
server (Phase 5), TUI (Phase 6), browser + frontend + packaging (Phase 7).

All commands run inside `nix develop` (stable 1.98.0, nightly
1.100.0-nightly 2026-08-24).

## Gates (workspace-wide)

| Gate | Command | Result |
|---|---|---|
| build | `RUSTFLAGS="-D warnings" cargo build --all-targets` | clean |
| build (release) | `cargo build --release` | clean |
| clippy | `cargo clippy --all-targets --all-features -- -D warnings` | clean |
| tests | `cargo test` | 169 passed (9 bin + 138 core + 7 server + 15 tui), 0 failed |
| miri | `MIRIFLAGS="-Zmiri-disable-isolation" cargo +nightly miri test -p echo-ai-core -- --skip session:: --skip tools::git:: --skip tools::shell:: --skip tools::process::` | 99 passed, 39 filtered |
| doc | `RUSTDOCFLAGS="-D warnings" cargo doc --document-private-items --no-deps` | clean |
| audit | `cargo audit` | 0 vulnerabilities |
| deny | `cargo deny check` | advisories/bans/licenses/sources ok |

## Bugs found and fixed (fail → pass)

1. **Ollama stream `done` shadowed by empty content chunk** — the final
   NDJSON line (`content:""`, `done:true`) matched the content branch
   first and never emitted `Done`. Fixed by checking `done` before
   content. `stream_accumulates_chunks_then_done`: FAILED → PASS.
2. **`AgentEvent`s sent with un-awaited futures** — `let _ = tx.send(..)`
   discarded the future, so nothing was delivered to frontends. All
   sends awaited; the bug was caught by the `unused future` clippy
   family, not a runtime test (the event loop would have appeared dead).
3. **`edit`/`write_file` change-tracker snapshots of absent files** —
   undo of a file *creation* was impossible (capture failed on missing
   files). `FileSnapshot.contents` is now `Option<Vec<u8>>`; undo
   removes the file. New regression test `undo_of_new_file_removes_it`.
4. **TF-IDF zero scores on single-document indexes** — raw `ln(N/df)`
   is 0 with one document, filtering every hit. Smoothed `ln(1+N/df)`.
   `index_and_search_roundtrip`: FAILED → PASS.
5. **HTML tag scanner never advanced past tags** — `<p>` emitted its own
   characters as text (`p>a b/p>`). `parse_tag` now returns the end
   index and the main loop consumes the tag. 2 extractor tests
   FAILED → PASS.
6. **axum 0.8 path syntax** — `:id` is rejected at router build; `{id}`
   is the 0.8 capture syntax. Caught by the bin's dispatch test.
7. **TUI backspace no-op at buffer end** — the boundary walk started at
   the cursor instead of before it. Codepoint-safety test FAILED → PASS.
8. **TUI loop never polled the keyboard** — the event select had no
   crossterm source; added `spawn_blocking(event::read)`. (Dead-code
   lints flagged the never-constructed `UiEvent::Key`.)

## Documented exceptions (scoped allows / config)

- `hashbrown` 0.14/0.17 + `syn` 2/3 duplicate pairs: crate-root
  `#![allow(clippy::multiple_crate_versions)]` in all four crates,
  `cargo deny` at warn, review doc entry.
- Poisoned-lock `expect_used` allows with `# Panics` docs (auth state,
  change tracker, semantic index, socket responders) — fail-fast policy.
- `paste` (RUSTSEC-2024-0436) and `rustls-pemfile` (RUSTSEC-2025-0134):
  unmaintained advisories, ignored in `deny.toml` with rationale
  (build-time macro / transitive ecosystem PEM loader; we no longer
  depend on the latter directly).
- `CDLA-Permissive-2.0` (webpki-roots) added to the license allowlist.
- Miri skip set: sqlite FFI + subprocess spawns are not
  Miri-interpretable; covered by ASan/UBSan/TSan CI stages.
- `too_many_lines`/`too_many_arguments` allows on the WS frame
  dispatcher, the TUI event loop, and `start_turn` — protocol tables and
  subsystem wiring, each with an in-code reason.

## Design deviations from the C version (reviewed)

- `utils/html.rs` one module instead of seven files; `llm/http.rs`
  mockable client replaces `curl_stub`; `REGISTRY_TEST` seam dissolved;
  rate-limiter persistence and `--chat` REPL dropped; delegate/Turnstile
  clicker/device-flow client deferred; frontend is static (no vite);
  session-JSON stores replaced by the single `SessionManager` vault.

## Test counts by area

core: agent 6 · browser 7 · change_tracker 6 · config 4 · llm 22 ·
safety 7 · session 27 · tools 43 · utils/html 6 · utils/misc 11 ·
bin 9 · server 7 · tui 15