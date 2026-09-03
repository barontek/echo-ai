#!/usr/bin/env bash
# debug-test.sh - run a single test in isolation. AGENTS.md "Testing":
# `cargo test <name> -- --exact --nocapture` for the one failing test,
# gdb/lldb attached for native debugging, `cargo miri test <name>` for
# unsafe/FFI code paths.
#
# Usage:
#   scripts/debug-test.sh <test-name>                 # exact + nocapture
#   scripts/debug-test.sh --gdb <test-name>           # under gdb (Linux)
#   scripts/debug-test.sh --lldb <test-name>          # under lldb (macOS)
#   scripts/debug-test.sh --miri <test-name>          # under Miri (nightly)
#   scripts/debug-test.sh --miri-gdb <test-name>      # Miri under gdb
#
# Extra arguments after the test name are forwarded to `cargo test`.
set -eu

mode="${1:?usage: debug-test.sh [--gdb|--lldb|--miri|--miri-gdb] <test-name> [cargo args...]}"
if [[ "$mode" == --* ]]; then
    test_name="${2:?usage: debug-test.sh [--gdb|--lldb|--miri|--miri-gdb] <test-name>}"
    shift 2
else
    test_name="$mode"
    mode="run"
    shift 1
fi

base=(test "$test_name" -- --exact --nocapture --test-threads=1)

case "$mode" in
    run)
        cargo "${base[@]}" "$@"
        ;;
    gdb)
        gdb -ex 'set follow-fork-mode child' -ex run --args cargo "${base[@]}" "$@"
        ;;
    lldb)
        lldb --batch -o 'settings set target.process.stop-on-sharedlibrary-events 0' -o run -- cargo "${base[@]}" "$@"
        ;;
    miri)
        # -Zmiri-disable-isolation: tests read the wall clock (message
        # timestamps, Fernet freshness); Miri's default isolation blocks
        # clock_gettime(REALTIME).
        MIRIFLAGS="-Zmiri-disable-isolation" cargo +nightly miri "${base[@]}" "$@"
        ;;
    miri-gdb)
        MIRIFLAGS="-Zmiri-disable-isolation" gdb -ex 'set follow-fork-mode child' -ex run --args cargo +nightly miri "${base[@]}" "$@"
        ;;
    *)
        echo "error: unknown mode: $mode" >&2
        exit 2
        ;;
esac