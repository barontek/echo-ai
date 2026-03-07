# vibe-ai

## What This Is

AI agent framework that orchestrates conversations between a user, an LLM, and a suite of tools. Supports Claude, OpenAI, and Ollama providers with a REPL-style loop. Includes CLI (TUI) and Streamlit web UI.

## Core Value

A programmable AI assistant that can execute tools autonomously while maintaining conversation context and session history.

## Requirements

### Validated

- ✓ CLI (TUI) with streaming output — existing
- ✓ Multi-provider LLM support (Claude, OpenAI, Ollama) — existing
- ✓ Tool execution framework with registry — existing
- ✓ Session persistence with SQLite — existing
- ✓ Safety/approval workflows — existing
- ✓ Web UI via Streamlit — existing

### Active

- [ ] Fix web UI Ollama config loading (reasoning model "thinks too much" only in web UI)
- [ ] Fix reasoning model verbosity (Qwen3.5 keeps "thinking" in responses)
- [ ] Improve performance (latency, token efficiency)
- [ ] Enhance error handling (retries, fallbacks, better messages)
- [ ] Improve tool execution (more reliable, better error categorization)
- [ ] Add new LLM providers if needed
- [ ] Improve user experience across CLI and web UI

### Out of Scope

- RAG/memory improvements — grep + read is more efficient
- Mobile app
- Cloud deployment

## Context

- **Current issue:** Qwen3.5:4b (reasoning model) works well in TUI but "thinks too much" in web UI. Likely config loading difference between the two interfaces.
- **User preference:** Prefers local models (Ollama) over API providers
- **Codebase state:** Already mapped via /gsd-map-codebase

## Constraints

- **Runtime:** Local models via Ollama (primary use case)
- **Persistence:** SQLite for sessions
- **No RAG:** User explicitly prefers grep + read over vector search

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Skip RAG | User prefers grep+read over vector search | — Pending |

---
*Last updated: 2026-03-08 after initial discussion*
