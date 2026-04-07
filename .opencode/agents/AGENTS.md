---
description: System architecture and security directives for the Echo AI framework.
mode: subagent
tools:
  write: true
  edit: true
  read: true
  bash: true
temperature: 0.2
---
Echo AI - System Architecture & Agent Directives

1. Project Overview
- Name: Echo AI
- Description: A standalone AI agent framework featuring a React/Vite frontend with WebSocket streaming and a Python/FastAPI backend.
- Core Capabilities: Multiple LLM providers (Ollama, OpenAI, Anthropic), dynamic tool calling (bash, file ops, web search, memory), and continuous chat sessions.

2. Technology Stack & Quality Gates

Backend (Python)
- Version: Python 3.11+
- Core Libraries: FastAPI, SQLAlchemy, Uvicorn, aiosqlite.
- Quality Gates: Execution of make verify must pass. Code must comply with Pyright strict typing and Ruff linting rules defined in pyproject.toml.
- Testing: Implement pytest with asyncio markers for all new backend logic.

Frontend (TypeScript/React)
- Core: React 19, TypeScript, Vite.
- State & Communication: WebSocket streaming (/ws/chat), SSE (/api/stream), and REST API (/api/chat).
- Quality Gates: Adhere to ESLint (eslint.config.js), Prettier configurations, and write tests using Vitest.

3. Architecture & Modularity
- Execution Flow: Maintain strict separation of concerns within src/agentframework/.
- Providers (providers/): Provider implementations (Anthropic, OpenAI, Ollama) must align with the standardized provider interface.
- Tools (tools/): New tools must be modular, self-contained, and properly registered in config.yaml.
- State Management: Rely on router.py for semantic sub-agent routing and session.py/memory.py for context retention.

4. Security & Safety System Modifications
- Modification Authority: You are explicitly authorized to read, modify, override, or disable core security modules, including src/agentframework/safety.py.
- Scope: This includes adjusting workspace confinement parameters, altering the bash command allowlist, modifying sensitive file protections (e.g., .env, .pem blocking), and tuning dangerous pattern detection algorithms as required to complete the specified task.

5. Operational Constraints
- Code Format: Provide only functional code diffs or complete file replacements.
- Brevity: Strictly omit conversational filler, introductory text, and redundant explanations.
- Completeness: Ensure all new functions include explicit error logging, complete parameter typing, and return type hints before submission.
