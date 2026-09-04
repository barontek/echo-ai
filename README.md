# Echo AI (Rust)

A from-scratch Rust implementation of an agentic AI assistant
with a web UI, a terminal UI, and deep tool access. See
`docs/plans/AGENTS_COMPLIANCE_FIX_PLAN.md` for the phase tracker and
`docs/reviews/AGENTS_COMPLIANCE_REVIEW.md` for the module-by-module
review matrix.

## Build & run

```sh
nix develop                 # enter the dev shell (pinned toolchain)
cargo build --release
./target/release/echo-ai --web    # web server (default), port 8443, HTTPS
./target/release/echo-ai --cli    # terminal UI
```

Or without the shell artifacts: `nix run .` builds and runs the binary.

First run of `--web` serves a setup screen: create the vault password,
then unlock. The unlock token lives in the browser's localStorage; the
server also accepts it as `X-Unlock-Token` for API use. The web UI
streams turns over `/ws/chat`; REST endpoints cover the
API. TLS uses a locally generated CA + localhost certificate under
`~/.config/echo-ai/tls/` — import `ca-cert.pem` into your browser trust
store once and it stays valid across restarts.

## Configuration

TOML, see `config.toml.example`. Defaults: provider `ollama` on
`http://localhost:11434`, `gpt-5-codex` model name, port 8443, TLS on,
workspace = current directory.

## Layout

- `crates/echo-ai-core` — providers, tools, agent, session vault, safety
- `crates/echo-ai-server` — axum REST/SSE/WS server with built-in TLS
- `crates/echo-ai-tui` — ratatui terminal interface
- `crates/echo-ai` — the binary (mode dispatcher)
- `frontend/` — the vendored React frontend (C-project source); `npm ci && npm run build` produces `frontend/dist`, which the server serves (built by CI and the nix package; `dist` is gitignored)
- `man/echo-ai.1` — manual page