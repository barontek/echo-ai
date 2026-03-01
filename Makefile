# Agent Framework Makefile

.PHONY: help install install-dev run chat test lint typecheck security clean sessions

help:
	@echo "Agent Framework - Available commands:"
	@echo ""
	@echo "  make install          - Install dependencies"
	@echo "  make install-dev     - Install with dev dependencies"
	@echo "  make chat            - Start chat mode (continuous conversation)"
	@echo "  make chat LOAD=name  - Load and resume a saved chat"
	@echo "  make run 'task'      - Run single task"
	@echo "  make test            - Run pytest test suite"
	@echo "  make lint            - Run ruff linter"
	@echo "  make typecheck       - Run pyright type checker"
	@echo "  make security        - Run security checks"
	@echo "  make chats           - List saved chats"
	@echo "  make clean           - Clean up sessions and cache"

install:
	python3 -m venv .venv
	.venv/bin/pip install -e .

install-dev:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

chat:
	.venv/bin/python -m agentframework.chat $(filter-out $@,$(MAKECMDGOALS))

run:
	.venv/bin/python -m agentframework.cli $(ARGS)

test:
	.venv/bin/pytest tests/ -v

lint:
	.venv/bin/ruff check src/

typecheck:
	.venv/bin/pyright src/

security:
	.venv/bin/safety check || true
	.venv/bin/bandit -r src/ || true

chats:
	@ls -la .agent_sessions/ 2>/dev/null || echo "No saved chats"

clean:
	rm -rf .agent_sessions/*.json
	rm -rf __pycache__ src/**/__pycache__
	find . -name "*.pyc" -delete
