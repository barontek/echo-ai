AGENTS.md — Rust Development Rules for Echo AI

This file governs how an AI coding agent writes, edits, and reviews Rust code in this repository. It's not a style preference doc — every rule exists to prevent a specific class of bug. Violations are build failures, not nitpicks.

Repository layout

This is a Cargo workspace: `crates/echo-ai-core`, `crates/echo-ai-server`, `crates/echo-ai-tui` (libraries), and `crates/echo-ai` (the `echo-ai` binary). Every `src/...` path reference in this file resolves per subsystem: core code (`agent`, `llm`, `tools`, `session`, `safety`, `config`, `change_tracker`, `utils`, `browser`) lives at `crates/echo-ai-core/src/...`, server code at `crates/echo-ai-server/src/...`, TUI code at `crates/echo-ai-tui/src/...`. Integration-test references (`tests/session_manager.rs`, `tests/db_crypto.rs`) resolve to the owning crate's `tests/` directory. This mirrors the C project's `src/` layout one-to-one.

Environment and toolchain

- Linux (NixOS): all builds and test runs happen inside `nix develop`. Never assume a system-installed Rust toolchain — if `nix develop` isn't active, the agent should not run `cargo`/`rustc` directly; it should either enter the shell first or flag that it's missing.
- macOS: use the project's pinned toolchain via `rust-toolchain.toml` at the repo root (channel + component list, e.g. `clippy`, `rustfmt`, `rust-src`, `llvm-tools-preview`). `rustup` reads this file automatically. `rustup show` output is recorded in CI logs for traceability. Sanitizer support (ASan/TSan) requires the nightly toolchain's `-Zsanitizer=...` flag; confirm the pinned nightly supports the same sanitizer set as the Linux build before running anything. UBSan is not in that set — rustc dropped the `-Z sanitizer=undefined` backend, so that UB class is covered by `overflow-checks = true` in every profile plus the Miri stage. LeakSanitizer is unsupported on macOS, so CI sets `ASAN_OPTIONS=detect_leaks=0` there — that is the one sanctioned deviation.
- Other/CI: any environment outside the two above must have its toolchain pinned via `rust-toolchain.toml` and documented before an agent runs a build in it — no ad hoc "whatever `rustup` resolves to" builds.
- An agent should never silently fall back to a toolchain other than the one pinned in `rust-toolchain.toml` when the expected dev shell isn't active — that's a "stop and ask" situation, not a "just try it" one.

Cross-platform portability

- Any `libc::` FFI call (subprocess signaling, low-level fd handling) is only as portable as the `libc` crate's per-platform bindings. If a symbol exists on Linux but not macOS (or vice versa), it fails at compile time behind the relevant `cfg`, but only if the macOS runner actually compiles that path. `process.rs`, `git.rs`, `python_execute.rs`, `server.rs`, `web_fetch.rs` all do subprocess/signal handling — each `cfg(unix)`/`cfg(target_os = "macos")` branch must be compiled by CI on both platforms, not just written and assumed correct.
- `tokio::process`/`std::process` behavior (signal delivery, fd inheritance, process-group semantics) differs subtly between Linux and macOS even through the same API. Any file spawning or reaping subprocesses must have a macOS CI job actually exercise that code path — a green Linux check doesn't mean the macOS branch is correct.
- When adding a new subprocess- or fd-handling function, write the platform-specific branch behind `cfg` up front and make sure both CI runners build and test it, rather than waiting for the macOS runner to complain.

Build flags

Build flags below assume the environment from the section above is active. Every crate must compile clean under:

`RUSTFLAGS="-D warnings" cargo build --all-targets` plus `cargo clippy --all-targets --all-features -- -D warnings`

Sanitizer builds (nightly, run as a separate CI stage — see Concurrency and Static analysis below):

`RUSTFLAGS="-Z sanitizer=address" cargo +nightly build -Z build-std --target <triple>` (and `=thread` per stage)

- If a `clippy` lint can't be fixed immediately, it gets a scoped `#[allow(clippy::lint_name)]` with a `// TODO(reason):` comment directly above it and a tracked issue — never a blanket `#![allow(...)]` at the crate root.
- Release builds add `--release` with `overflow-checks = true` and `debug-assertions = true` kept on in `Cargo.toml`'s `[profile.release]` for CI — sanitizers stay on in CI even for "release" test runs.
- Never widen `#![allow(...)]` at crate or module scope to "get it compiling." Fix the underlying issue or ask.
- `unsafe` blocks require a `// SAFETY:` comment immediately above them stating the invariant that makes them sound. No `unsafe` without one — this is a build-reviewable requirement, not a suggestion.

Static analysis

- `cargo clippy` (with `clippy::all`, `clippy::pedantic` reviewed and selectively enabled, `clippy::cargo`) and `cargo audit` (dependency vulnerability scan) are a CI gate, run separately from the sanitizer/test run — sanitizers only catch bugs on lines a test actually runs; clippy's pedantic/suspicious lints and `cargo audit`'s advisory-DB check catch classes sanitizers can't reach.
- `cargo deny check` (license + duplicate-dependency + advisory check) runs alongside `cargo audit` as part of the same gate.
- Findings are treated the same as a compiler warning under `-D warnings` — fix it or get a documented `#[allow(clippy::lint_name)] // TODO(reason:)` exception, never a blanket module- or crate-level allow.
- An `#[allow(clippy::missing_safety_doc)]` (or any allow suppressing an `unsafe`-adjacent lint) must cite the specific invariant it's asserting — never a prose "it's fine, trust me" claim. Template: `src/utils/html_assembly.rs:59`.
- Purpose is to catch gaps like the ones in "Known gaps" before a human has to notice and write the fault-injection test for them.

Concurrency

- Rust's `Send`/`Sync` traits and the borrow checker eliminate most data-race bugs at compile time for safe code — but `unsafe`, FFI, and async runtimes (tokio) can silently punch through that guarantee (raw pointers crossing threads, `unsafe impl Send`, interior-mutability misuse under a shared `Arc`).
- Any file touching shared or global state across more than one thread or task — subprocess spawning, async LLM/tool calls, server request handling — gets a ThreadSanitizer (TSan, nightly `-Z sanitizer=thread`) build/run for any `unsafe` or FFI-adjacent path in that file.
- For pure-safe-Rust concurrency (no `unsafe`, no FFI), `loom` model-checking tests are the primary tool — loom exhaustively explores thread interleavings for a piece of concurrent logic rather than sampling one execution.
- TSan and loom runs are separate CI stages from the ASan/clippy/test run.
- A thread-safety claim in a doc comment (Documentation standards item 4) needs a TSan or loom run backing it, not just the comment. `unsafe impl Send`/`unsafe impl Sync` is itself a thread-safety claim and needs the same backing.

Memory ownership

- Rust's ownership model (move semantics, borrowing, lifetimes) enforces ownership discipline at compile time for safe code. This section applies specifically to: `unsafe` blocks, FFI boundaries, and `Rc`/`Arc`-based shared ownership where the compiler can't fully reason about lifetime for you.
- Every function returning an owned allocation across an FFI boundary (`Box::into_raw`, `CString::into_raw`, etc.) must document who calls the matching `from_raw`/`_free` and when.
- No implicit ownership transfer through global/`static` state. If a type owns a resource, its `Drop` impl releases it — no manual "someone else remembers to free this" convention. Prefer RAII (`Drop`) over any hand-rolled cleanup function.
- Every `unsafe`-obtained resource (raw allocation, FFI handle, mmap'd region) has a release on every exit path, including error/panic paths — wrap it in a `Drop`-implementing guard type rather than relying on manual cleanup at each `return`/`?`.
- Double-free and use-after-free are only reachable through `unsafe` in this codebase — any `unsafe` block that manipulates a raw pointer's lifetime gets the same audit rigor as any security bug, including a `// SAFETY:` comment explaining why the access is valid at that point.
- Prefer `Arc<Mutex<T>>`/`Arc<RwLock<T>>` over raw pointers for cross-thread shared ownership; reach for raw pointers and `unsafe` only when the safe abstractions can't express what's needed, and justify that choice in the same commit.

Error handling

- Every function that can fail returns `Result<T, E>` — never a bare success-assuming return with a `.unwrap()`/`.expect()` "should work" assumption outside tests, examples, or a `main()` that's about to exit anyway.
- Every fallible call is checked, via `?` or an explicit `match`. `.unwrap()` on a `Result`/`Option` in library or application code (not test code) is a `clippy::unwrap_used` violation and gets rejected in review.
- No silent failure paths — propagate the error with `?` or log-and-return with context, never `let _ = fallible_call();` to discard an error.
- Errors carry context (what operation, what input) via a project-wide error type (`thiserror`-derived enums per module, wrapped in `anyhow`/a project `Error` at application boundaries) — not a bare error string or a bare downstream error with no added context.

No undefined behavior

- No signed integer overflow relied on for wraparound — `overflow-checks = true` in every profile makes this a panic in debug and CI; use `wrapping_*`/`checked_*`/`saturating_*` explicitly when wraparound or saturation is the actual intent.
- No unsound transmutes or strict-aliasing violations — any `std::mem::transmute` needs a `// SAFETY:` comment justifying layout compatibility, and is avoided in favor of safe alternatives (`as` casts, `From`/`TryFrom`, `bytemuck`) wherever one exists.
- No use of uninitialized memory — `MaybeUninit` is the only sanctioned tool for genuinely uninitialized state, and every use needs a `// SAFETY:` comment showing every field is initialized before the value is treated as valid.
- No out-of-bounds pointer arithmetic "because it'll probably still be valid" — this only applies inside `unsafe` blocks doing raw pointer work, and those get bounds-checked before dereference with the check visible in the diff.
- No panics as an error-handling mechanism in library/application code paths — `unwrap`/`expect`/`panic!`/array-index-that-can-panic are reserved for genuine programmer-error invariant violations, not for reachable failure conditions like malformed input or I/O errors.

Structure and modules

- One module per responsibility: `mod foo;` in `foo.rs` (or `foo/mod.rs` for a module with children), not one giant file absorbing multiple concerns.
- No circular module dependencies. Documented exceptions: (1) the tool modules under `src/tools/` share one subsystem contract via a `Tool` trait and a `registry` module; per-tool trait-object boilerplate would only duplicate that shared contract, so they intentionally depend on `tool.rs`/`registry.rs` rather than each other. (2) `src/llm/provider.rs` defines a shared `LlmProvider` trait with no corresponding "impl file" of its own.
- Default to private visibility, use `pub(crate)` for cross-module-but-internal APIs, and reserve `pub` for the crate's actual public surface. A `pub` item that doesn't need to be leaks internals.
- No function longer than ~60 lines without a strong reason.
- Public functions carry doc comments stating ownership and failure modes — see Documentation standards below.

Code style

File size

- No hard line limit, but treat 300-800 lines as comfortable and 1000+ as a signal to split.
- Split along responsibility boundaries, not arbitrary line counts. If you can't describe what a module does in one sentence without "and," it's doing too much.
- Mirror module boundaries with source files (`parser.rs`, `lexer.rs`, `hashtable.rs`) instead of letting a catch-all `utils.rs` absorb everything.
- A file with 15+ public items (functions, types, impls) is usually mixing concerns even if each item is short.
- A large pile of private helper functions backing one public function/impl is a good candidate to split into its own module.

Functions

- Functions should be short and do one thing well.
- Minimize nesting depth. Prefer early returns (`?`, `let else`, guard clauses) over deep `if`/`match` nesting.
- One statement per line. Prefer explicit `let` bindings with a clear type over cramming multi-step logic into one chained expression — a long iterator chain that needs a comment to explain each `.map`/`.filter` step should usually be broken into named intermediate bindings.

Naming

- Short, terse names are fine for local variables with small scope (loop counters, short-lived temporaries).
- Use descriptive names for anything with wider scope (public items, `pub(crate)` functions, type names).
- Avoid newtype wrappers that hide what's underneath without adding a real invariant. A newtype should exist to enforce a constraint (`UserId(u64)` preventing mixing with other `u64`s) or a lifetime/ownership distinction — not just to rename a primitive.
- Follow standard Rust casing (`snake_case` functions/modules, `CamelCase` types/traits, `SCREAMING_SNAKE_CASE` consts) — enforced by `rustfmt`/`clippy::all`.

Comments

- Comment WHY the code does something, not WHAT it does. Every non-obvious line gets a short comment explaining why, not what.
- Avoid comments inside a function body except `// SAFETY:` comments on `unsafe` blocks, which are mandatory. If a function needs other inline explanation, that's usually a sign it should be split up.
- Put explanatory comments at the top of a function: what it does, and why, if that's not obvious from the name and signature.
- Don't write comments that just restate the function signature or what the type system already expresses.

General philosophy

- Boring is good — the obvious, explicit version of a function beats a clever one-liner with iterator-adapter or macro tricks.
- Consistency matters more than which specific convention you pick. Choose a style (`rustfmt` defaults, unless the project overrides them in `rustfmt.toml`) and apply it uniformly across the project.
- Prefer clarity over cleverness. Code that looks obvious after 20 straight hours of staring at a screen is doing its job.

Documentation standards

Use `///` doc comments for all public items (anything `pub` or `pub(crate)` that other modules consume):

/// Opens a connection to the database.
///
/// # Arguments
/// * `path` - path to the SQLite file.
/// * `flags` - `DbFlags::READONLY` or `DbFlags::CREATE`.
///
/// # Returns
/// A `DbConn` on success.
///
/// # Errors
/// Returns `DbError::Open` if the file can't be opened or created,
/// wrapping the underlying `sqlite` error.
pub fn db_open(path: &Path, flags: DbFlags) -> Result<DbConn, DbError> {
    // ...
}

Where docs live:

- The doc comment above the `pub`/`pub(crate)` item carries the contract — this is what someone integrates against without reading the function body, and it's what `cargo doc` renders.
- The function/impl body carries the "why," not the "what." Inline comments explain non-obvious decisions, invariants, or workarounds — never restate what the code already says. `// SAFETY:` comments on `unsafe` blocks are the one mandatory exception.
- File-level doc comment (`//!` at the top of the file) on every module: one or two lines on what the module is responsible for and what it depends on.

//! Fernet-based field-level encryption for session records.
//! Depends on: `sqlx` (sqlite), `fernet`.

Non-negotiable per public function/type:

1. Ownership — for anything crossing an `unsafe`/FFI boundary: who allocates, who frees, via which call. For safe Rust, the signature already states this (owned vs `&`/`&mut`) — don't restate it in prose.
2. Lifetime — beyond what the borrow checker enforces: if a returned value's validity depends on something not expressible in the type (an external resource, a raw pointer from FFI), say so explicitly.
3. Nullability / absence — `Option<T>` tells you it *can* be `None`; the doc comment says *when*/*why* (not-found vs not-loaded-yet vs intentionally cleared).
4. Thread-safety — safe to call concurrently? Does it touch shared/`static` state? For `unsafe impl Send`/`Sync`, this is mandatory.
5. Error signaling — which `Result<_, E>` variant maps to which failure condition; document under a `# Errors` section, consistently across the whole codebase.
6. Panics — under a `# Panics` section, any input or state that makes the function panic instead of returning `Err`. If the list is non-empty, treat it as a signal the function should probably return `Result` instead.

General rules

- Document the interface, not the implementation. If a doc comment needs to change every time the function body changes without its behavior changing, it's in the wrong place.
- Don't restate what the type system already says (`/// the id` above `id: String` is noise) — comment intent and invariants the type can't encode, not mechanics.
- Update the doc comment in the same commit as the code change. Stale docs are worse than no docs. `cargo doc --document-private-items` run in CI catches broken intra-doc links as a lightweight staleness check.
- One `README.md` or module-level `//!` doc per module/subsystem, not per function.
- Consistency over cleverness: one doc-comment format, enforced by `cargo clippy`'s `missing_docs`-family lints on `pub` items where the project has them enabled.
- When `unsafe`/FFI code is touched by other tooling (bindings, agent code review), be extra explicit about ownership/lifetime in doc comments — that's the bug class invisible to a reviewer unless it's spelled out.

Testing

- Every new function with a non-trivial contract gets a `#[test]` (or `#[tokio::test]` for async), run through `cargo test`.
- Every bug fix includes a regression test that would have caught it, added before the fix is marked resolved — the agent demonstrates it fails on the old code and passes on the new code (`git stash`, rerun, unstash), doesn't just assert it.
- `cargo fuzz` (libFuzzer-backed) targets required for any function parsing external input (files, network data, session blobs, tool output).
- `cargo test` runs clean under ASan (nightly `-Z sanitizer=address`) as a merge requirement, not optional CI noise. UBSan is not runnable on the pinned nightly (rustc removed the `undefined` backend); UB coverage relies on `overflow-checks = true` and the Miri stage instead.

Test file organization

- Prefer inline `#[cfg(test)] mod tests { ... }` at the bottom of the source file for unit tests — idiomatic Rust convention, keeps the test close to what it exercises.
- Integration tests (exercising the crate's public API as an external consumer would) go in `tests/`, one file per behavior area, named to match what's under test (`tests/session_manager.rs`, `tests/db_crypto.rs`).
- Don't let one integration test file grow to cover multiple unrelated subsystems just because it's convenient. Split it the same way you'd split a source module that's doing too much.
- Group related test cases together with a clear naming pattern, e.g. `<function>_<scenario>` (`parse_input_empty_string`, `parse_input_null_pointer_equivalent`).

Size and scope

- Same rough guidance as source files: a test module/file that's grown past ~800-1000 lines is worth splitting, usually by feature or by which function/module is under test.
- One test function should test one behavior. If a single `#[test]` fn is asserting many unrelated things, split it.
- Prefer many small, focused tests over few large ones that try to cover everything at once. A failing test name should tell you what broke without reading the test body.

Independence and repeatability

- Tests should not depend on execution order or on state left behind by another test — `cargo test` runs tests in parallel by default, so order-dependence surfaces as flakiness fast; treat any flaky test as a bug in the test, not a reason to add `--test-threads=1`.
- Avoid shared mutable global/`static` state between tests unless it's properly synchronized and reset per test.
- Tests should be deterministic. Avoid relying on timing, uninitialized memory, or system-specific behavior unless that's specifically what's being tested.

What to test

- Cover the normal case, boundary conditions, and error/failure paths (`None`/empty input, zero-length input, allocation failure via `try_reserve` where applicable), not just the happy path.
- Test behavior and output, not implementation details. Tests that assert on private internal state make refactoring painful without adding much safety — test through the `pub`/`pub(crate)` surface.

Test comments

- Same rule as source: comment why a test exists or why an edge case matters, not what the assertion does line by line.
- If a test is a regression test for a specific bug, note that in a short comment (or the test name) so future readers know why it exists.

Test framework conventions

- One test module per source module or behavior area (`mod tests` per file, or one `tests/*.rs` file per behavior area for integration tests) — never one flat file for the whole crate.
- Test names state the specific claim being falsified: `unlock_rejects_wrong_password`, not `test_unlock`.
- Use `assert_eq!`/`assert_ne!`/`assert!` with a descriptive message argument where the default output wouldn't make the failure obvious — `assert_eq!` already prints expected vs. actual.
- Fixtures via a small `fn setup() -> Fixture` helper called at the top of each test, or a `rstest`-style `#[fixture]` if the project adopts that crate, for per-test state.
- Set an explicit timeout for any test touching I/O, locking, or anything that can hang — via `#[tokio::test(flavor = "multi_thread")]` combined with `tokio::time::timeout(...)` wrapping the awaited call.
- Debugging a failure: run the single test directly (`cargo test <name> -- --exact --nocapture`) and attach `gdb`/`lldb` to that process.
- Build/registration is automatic via `#[test]` attribute discovery. `cargo nextest` is the recommended runner for CI (better parallelism and per-test timeout support than default `cargo test`).

Verification discipline

- An agent's claim that something "works" or "is fixed" isn't sufficient — show the actual failing test before the fix and the passing one after, and for memory/unsafe bugs, a clean ASan/Miri run.
- `git stash` and rerun the previous behavior when a fix is claimed, to confirm the bug reproduces on old code and is gone on new code.
- `cargo +nightly miri test` is required for any `unsafe` code path touched by a fix — Miri catches undefined behavior (invalid pointer use, aliasing violations, uninitialized reads) that even ASan can miss.
- Audit findings — from the agent itself or a second reviewing agent — aren't accepted at face value; verify via actual code path tracing with specific line numbers before marking fixed.
- No fix touching `unsafe` code is "done" until it's run under Miri and the relevant sanitizer at least once.
- Fail→pass test evidence and sanitizer/Miri output cited as proof of a fix must come from an actual command invocation in that session — show the raw command and its output, not a paraphrase or a claim that it was run.
- Any new function with a non-trivial multi-step commit path (the "Fault-injection testing" pattern below) ships its fault-injection test in the same PR, or the PR is blocked — enforced as a CI check, not a reviewer-remembers-to-check convention.

Fault-injection testing (partial-commit regression tests)

Safe Rust's default `Vec`/`String`/`Box` allocation aborts the process on OOM rather than returning an error, so a classic "forgot to check malloc's return" bug mostly can't happen. The underlying hazard — a partial commit on a failure partway through a multi-step operation — still can, wherever the failure source is a fallible I/O write, a DB insert, an FFI call, or an explicit `try_reserve`.

The pattern, in order of how much of the target function's surrounding code it needs:

Simple case — a single module, no external dependencies, testing `try_reserve`-based fallible allocation directly. Rust's std collections expose `try_reserve`/`try_reserve_exact`, which return `Result<(), TryReserveError>` instead of aborting — use these directly in the function under test where partial-commit safety matters, and force the failure in the test via a request for an allocation size known to exceed available memory:

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn commit_batch_rolls_back_on_reserve_failure() {
        let mut batch = Batch::new();
        // Force try_reserve to fail deterministically rather than depending
        // on actual system OOM, which isn't reproducible on demand.
        let result = batch.try_commit_n(usize::MAX);
        assert!(result.is_err());
        assert_eq!(batch.count(), 0, "partial commit leaked into count");
    }
}

The test asserts: the function returns an error, nothing partial got committed (count unchanged, no dangling entry), and everything allocated before the failure point was released (checked via `Drop` running, or under Miri/ASan for `unsafe` paths).

Harder case — the function under test pulls in real dependencies you don't want in a unit test (a DB, an LLM provider, a fallible external call you want to fail on demand). Two techniques, used together as needed:

- Define a trait for the fallible operation (`trait Store { fn insert(&mut self, ...) -> Result<(), StoreError>; }`) and inject a test-only mock implementation (hand-written, or via `mockall`) that fails on the Nth call.
- A `#[cfg(test)]`-gated constructor or test-only feature flag around a heavy init path, when the dependency is baked into initialization rather than a single call (see `registry.rs`'s `#[cfg(feature = "registry_test")]` guard, which skips wiring up the full tool registry so the test binary doesn't have to link everything `registry.rs` would normally pull in).

The goal in both cases is the same: isolate the fallible-commit logic from the I/O/provider logic so the fault-injection test only exercises the part that can actually have this bug — you don't need a live LLM or DB to prove a partial-commit path is handled correctly.

When to reach for this: any function that performs more than one fallible step and then commits a count, index, or struct based on those steps succeeding. If you're writing or reviewing such a function and it doesn't have a fault-injection test, write the test before considering the function done, not after something breaks. Treat every `.unwrap()` you're tempted to write in a multi-step commit function as a sign this pattern applies.

Known gaps: to be tracked in `AGENTS_COMPLIANCE_REVIEW.md` as modules are written — every module with multi-step fallible commit logic should get a fault-injection test before merge, not after a production crash.

Verification discipline: every bug fix ships with a regression test that fails on the old code and passes on the new; the fail→pass evidence (test name, sanitizer/Miri output) is archived in `docs/verification/` and tracked in `docs/plans/AGENTS_COMPLIANCE_FIX_PLAN.md`. Single-test debugging uses `scripts/debug-test.sh` (`cargo test <name> -- --exact --nocapture`, plus `gdb`/`lldb`/`cargo miri test <name>` isolation).

When to stop and ask

- If a change would require a scoped `#[allow(clippy::...)]` without a documented reason, an `unsafe` block without a `// SAFETY:` comment, or skipping a test to land — stop and ask, don't route around it.
- When in doubt about a memory-safety or concurrency tradeoff — especially anything touching `unsafe`, raw pointers, or `Send`/`Sync` impls — ask rather than guess.
