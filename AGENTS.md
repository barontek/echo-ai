# AGENTS.md

## ⚠️ Never Reference Deleted Modules
- **sentry** (`src/agentframework/sentry.py`, `@sentry/react`) — removed entirely. Do not import or reference it.
- **nicegui** (`src/agentframework/ui_nicegui/`) — removed entirely. Do not import or reference it.

## Commands

```bash
# Backend — Linux: run inside `nix develop`. macOS/Windows: prefix with `uv run`.
#   Linux:   make verify
#   macOS:   uv run make verify
make verify           # canonical quality gate: pytest → ruff → pyright (run this before any PR)
make test             # pytest with coverage only
make lint             # ruff check
make typecheck        # pyright src/
make security         # pip-audit + bandit (blocked on NixOS)

# Frontend
cd frontend && npm run typecheck && npm run lint && npm run test:run && npm run build  # canonical: typecheck + lint + test + build
cd frontend && npm run test:run     # vitest only
cd frontend && npm run lint
cd frontend && npm run typecheck
cd frontend && npm run build
```

## Architecture

- **Python package**: `src/agentframework/` (pyproject.toml)
- **Entry points**: `agent` (CLI), `agentframework.chat` (interactive), `agentframework.web_api` (FastAPI)
- **Frontend entry**: `frontend/src/main.tsx`
- **Session storage**: SQLite in `~/.echo-ai/sessions/`
- **Routing/state**: `router.py` (semantic sub-agent routing), `session.py` / `memory.py`
- **Providers**: `src/agentframework/providers/` — Anthropic, OpenAI, Ollama. Must implement the standardized interface.
- **Tools**: `src/agentframework/tools/` — modular, self-contained, registered in `config.yaml`
- **Deep search**: `src/agentframework/tools/deep_search.py` — fetch → filter → summarize pipeline
- **Search providers**: `src/agentframework/tools/search_providers/` — Brave, DuckDuckGo, Tavily

## Sub-Agent Delegation

1. Sub-agents are registered via `agent.register_sub_agent()`
2. The first registration lazily creates a `DelegateTool` and adds it to the tool map
3. `DelegateTool` spawns a transient `Agent` with no session, sharing the root agent's LLM provider
4. The result is returned as a `ToolResult` string

## Frontend Communication

- WebSocket: `/ws/chat`
- SSE streaming: `/api/stream`
- REST: `/api/chat`

## Key Constraints

- **Python 3.11+** required
- **Always use `nix develop`** (Linux) — auto-syncs deps, sets up venv, provides all tooling. On macOS/Windows, use `uv run` directly.
- **Package management**: `uv` only. Never use `pip` directly.
- **PYTHONPATH**: must be `src` when running tests (`PYTHONPATH=src pytest ...`)
- **Pre-commit**: runs on `git commit`. Run manually with `pre-commit run --all-files`.
- **Pyright strict** typing required on all backend code.
- All new functions: explicit error logging, complete parameter typing, return type hints.
- Use `pytest.mark.asyncio` for async backend tests.
- Provide functional code diffs only — no conversational filler.

## Database Encryption & Background Services

Session data is encrypted at rest via Fernet (AES-128-CBC + HMAC-SHA256). The key
is derived from a user-chosen password using Scrypt (N=2¹⁴, r=8, p=1, 32-byte key).

- **CLI / interactive**: you are prompted for the password once per process start.
- **web_api.py as a background service** (systemd, launchd, Docker): there is no TTY
  to prompt on, so you **must** set `ECHO_DB_PASSWORD` in the service environment.
  Example systemd unit fragment:
  ```
  [Service]
  Environment=ECHO_DB_PASSWORD=your-strong-password
  ```
  This is **weaker** than an interactive prompt — anything that can read the process
  environment (e.g. `/proc/<pid>/environ`, debuggers, other processes running as the
  same user) can recover the password. This is a known trade-off; it prevents casual
  disk-level access to session data but does **not** protect against an attacker with
  OS-level access.

## Security Module

`src/agentframework/safety.py` controls workspace confinement, bash allowlist, sensitive file protections, and dangerous pattern detection.

You may read and modify this file. Before disabling or weakening any check, state explicitly what you are changing and why. Do not remove protections wholesale — patch only what is necessary.

## Test Writing Rules

### The one rule that matters most
Expected values must come from the **spec or requirement**, never by mentally running
the code and copying the output. If no spec exists, state the assumption in a comment.

### Every test must be falsifiable
Before finalizing a test, ask: "what bug would make this fail?"
If the answer is "none I can think of", rewrite it.
`assert result is not None` is never a meaningful assertion.

### Always test these edge cases unless the signature makes them impossible
- Empty input (string, list, dict)
- Zero, negative numbers
- None / missing optional args
- Boundary values (first, last, min, max)

### Naming
`test_<function>_<scenario>_<expected_outcome>` — not just `test_<function>`.

### After writing tests, always output
"What these tests would catch: ..." with 3–5 concrete bugs that would cause failures.
This is mandatory, not optional.

### When improving existing tests
- Replace assertions where the expected value was derived from the code itself
- Flag any test that would pass if the function returned a hardcoded value
- Add edge cases if only happy path is covered

### Mocks
Mock behavior must match the real contract of the dependency.
Never mock the thing being tested.
