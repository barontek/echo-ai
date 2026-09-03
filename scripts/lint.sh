#!/usr/bin/env bash
# lint.sh - local mirror of the CI lint gate (AGENTS.md "Build flags" and
# "Static analysis"). Runs fmt, clippy with -D warnings, and the doc build
# with -D warnings (catches broken intra-doc links, per AGENTS.md
# "Documentation standards"). Must run inside `nix develop`.
set -eu

echo "== fmt =="
cargo fmt --all -- --check

echo "== clippy =="
cargo clippy --all-targets --all-features -- -D warnings

echo "== build (-D warnings) =="
RUSTFLAGS="-D warnings" cargo build --all-targets

echo "== doc =="
RUSTDOCFLAGS="-D warnings" cargo doc --document-private-items