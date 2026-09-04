# Phase 0 — Scaffold verification evidence

**Date:** 2026-09-03
**Repo:** /home/barontek/echo-ai-rust
**Scope:** workspace scaffolding, toolchain pinning, CI gates, scripts, compliance docs.

All commands run inside `nix develop` (flake.lock 2026-09-03; stable 1.98.0, nightly 1.100.0-nightly 2026-08-24).

## Toolchain

```
cargo 1.98.0 (797e8a9bc 2026-08-05)
rustc +nightly: 1.100.0-nightly (e7769602a 2026-08-24)
cargo +nightly miri: miri 0.1.0 (e7769602ac 2026-08-24)
cargo +nightly clippy: clippy 0.1.100 (e7769602ac 2026-08-24)
```

Notable fix: the rust-overlay rustup shim's `toolchain link` copies the
nix-store toolchain and drops extension components (`cargo-miri`,
rust-src). The dev-shell `shellHook` now bypasses it with a direct
symlink (`ln -s ${nightly} ~/.rustup/toolchains/nightly-...`); verified
idempotent from a clean state (`rm -rf` of the toolchain dir, re-enter
shell, all `+nightly` commands resolve).

## Gates

| Gate | Command | Result |
|---|---|---|
| build | `RUSTFLAGS="-D warnings" cargo build --all-targets` | clean |
| fmt | `cargo fmt --all -- --check` | clean (after `cargo fmt --all`) |
| clippy | `cargo clippy --all-targets --all-features -- -D warnings` | clean |
| doc | `RUSTDOCFLAGS="-D warnings" cargo doc --document-private-items --no-deps` | clean |
| unit tests | `cargo test` | 9 passed (echo-ai arg parsing + run()) |
| nextest | `cargo nextest run` | 9 passed, 0 skipped |
| miri | `cargo +nightly miri test -p echo-ai-core` | clean (0 tests — first real tests land Phase 1) |
| audit | `cargo audit` | 0 vulnerabilities (1239 advisories loaded) |
| deny | `cargo deny check` | advisories/bans/licenses/sources ok |
| file lengths | `scripts/check-file-lengths.sh` | largest .rs: 204 lines (band 300-800) |
| ASan | `RUSTFLAGS="-Z sanitizer=address -D warnings" cargo +nightly test -Z build-std --target x86_64-unknown-linux-gnu --all --locked` | clean |

Clippy findings fixed during this pass: `cargo_common_metadata` (added
readme/keywords/categories + per-crate READMEs), `doc_markdown` (backtick
`RustCrypto`/`WebSocket`/`SSE`/`TLS`/`PEM`/`CORS`/`HTTPS`/`HTTP`/
`CommonMark`), `no_effect_underscore_binding` + `dead_code` (run()
now validates an explicitly-configured `--config` path existence —
fail-fast on typos, with regression test).

## CI

.github/workflows/ci.yml written but not yet exercised on GitHub
(pending initial commit + push to barontek/echo-ai). The ASan stage
command was reproduced locally (row above); UBSan/TSan stages use the
same invocation with `-Z sanitizer=undefined|thread`.