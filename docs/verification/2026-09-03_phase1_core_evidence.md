# Phase 1 — Core plane verification evidence

**Date:** 2026-09-03
**Repo:** /home/barontek/echo-ai-rust
**Scope:** config (TOML), utils (logging/string/metrics/circuit_breaker/rate_limiter), safety, session store (Fernet + scrypt + SQLite + migration), change tracker, bin wiring.

All commands run inside `nix develop` (stable 1.98.0, nightly 1.100.0-nightly 2026-08-24).

## Gates

| Gate | Command | Result |
|---|---|---|
| build | `RUSTFLAGS="-D warnings" cargo build --all-targets` | clean |
| fmt | `cargo fmt --all -- --check` | clean |
| clippy | `cargo clippy --all-targets --all-features -- -D warnings` | clean (exceptions below) |
| doc | `RUSTDOCFLAGS="-D warnings" cargo doc --document-private-items --no-deps` | clean |
| tests | `cargo test` | 74 passed (9 bin + 65 core), 0 failed |
| miri | `MIRIFLAGS="-Zmiri-disable-isolation" cargo +nightly miri test -p echo-ai-core -- --skip session::` | 35 passed, 30 filtered |
| audit | `cargo audit` | 0 vulnerabilities (89 deps) |
| deny | `cargo deny check` | advisories/bans/licenses/sources ok |

## Bugs found and fixed during the phase (fail → pass)

1. **Circuit breaker state inverted** — `is_open()` returned `true` (reject) for every state except an *expired* `OPEN`. All four breaker tests failed; fix: `is_open` = `matches!(self.state(), State::Open { .. })` (the state helper already promotes expired `OPEN`→`HALF_OPEN`). Tests `trips_after_threshold_and_stays_open_during_cooldown`, `opens_then_half_opens_and_closes_on_probe_success`, `half_open_failure_reopens`, `success_resets_failure_count`: FAILED → PASS.
2. **Fernet decrypt fed the IV in as the first ciphertext block** — `decrypt` sliced `token[9..ciphertext_end]`, but `ciphertext_end = len - HMAC` *includes* the 16-byte IV. Result: 16 bytes of garbage + correct tail, exact signature of "IV treated as block 1". Fixed to `token[9 + IV_SIZE..ciphertext_end]`. Tests `encrypt_decrypt_roundtrip`, `token_layout_matches_c_spec`, `verifier_check_distinguishes_passwords`, and every manager/migration test that cascaded from it: FAILED → PASS. Probe evidence: token hex `80|ts|iv|ct|hmac` with garbage+plaintext decrypt, then clean roundtrip after fix.
3. **`canonicalize_deepest` appended a trailing `/`** for fully-existing targets (empty remainder join), breaking suffix blocklists (`.env/` doesn't end with `.env`). Fixed with an empty-remainder branch. `default_blocklists_apply`, `configured_blocklist_replaces_defaults`: FAILED → PASS.
4. **Test isolation races** — shared temp-dir names across parallel tests in one process (safety, memory). Fixed with per-test unique dirs (counter-suffixed). Races reproduced as order-dependent failures, gone after fix.
5. **Migration test simulation bug** — the post-commit recovery test didn't recreate `.verifier.new`, so recovery hit a missing-file `Io` error instead of the wrong-password `Crypto` path. Test now writes a real `.verifier.new` under the new key (matching the true crash window).

## Documented exceptions (per AGENTS.md scoped-allow discipline)

- `clippy::multiple_crate_versions` crate-root allow: `hashbrown` 0.14/0.17 (rusqlite→hashlink vs toml→indexmap) and `syn` 2/3 (proc-macro generations) are unavoidable transitive pairs; `cargo deny` reports them at warn (deny.toml).
- `clippy::expect_used` scoped allows with invariant comments: `Hmac::new_from_slice` on a fixed 16-byte slice (cannot fail), and mutex-poison fail-fast policy (session manager, metrics, rate limiter, circuit breaker — a poisoned lock means continuing could corrupt the vault, so failing fast is the safe choice).
- `clippy::missing_panics_doc` + `# Panics` docs on the same two HMAC sites.
- Cast lints on the `observe` micros conversion: bounds-checked clamp documented in-code.
- Miri flags: `-Zmiri-disable-isolation` (wall-clock reads) and `--skip session::` (rusqlite is bundled C FFI; covered by ASan/UBSan/TSan stages instead).

## Compatibility notes

- DB schema, Fernet token layout, scrypt params, and key-material file layout are byte-compatible with the vault format (`agent_sessions`/`provider_oauth`/`user_memory`; `0x80|ts|iv|ct|hmac`; N=2^18 r=8 p=1; `salt`/`.pepper`/`.verifier`, 0600 files, 0700 dir).
- Rate limiter persistence (C: `rate_limits.db`) deliberately not ported — in-memory windows reset on restart, which is the fail-open behavior anyway (documented in module docs).

## Test counts by module

agent/message 4 · change_tracker 5 · config 4 · safety 7 · session/db 2 · session/encryption 9 · session/manager 9 · session/memory 4 · session/migration 3 · utils/circuit_breaker 4 · utils/logging 2 · utils/metrics 3 · utils/rate_limiter 3 · utils/string_utils 3 · bin (arg parsing + config fail-fast) 9