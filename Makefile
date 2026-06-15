# Agent Framework Makefile

.PHONY: help install run chat test lint typecheck verify security bench clean sessions frontend-test frontend-lint frontend-build frontend-check

help:
	@echo "Agent Framework - Available commands:"
	@echo ""
	@echo "  make install          - Install dependencies"
	@echo "  make chat            - Start chat mode (continuous conversation)"
	@echo "  make chat LOAD=name  - Load and resume a saved chat"
	@echo "  make run 'task'      - Run single task"
	@echo "  make test            - Run pytest test suite"
	@echo "  make lint            - Run ruff linter"
	@echo "  make typecheck       - Run pyright type checker"
	@echo "  make security        - Run security checks"
	@echo "  make bench           - Run benchmark harness"
	@echo "  make serve-docs      - Serve MkDocs documentation locally"
	@echo "  make chats           - List saved chats"
	@echo "  make lock            - Generate strict dependencies using uv"
	@echo "  make setup-precommit - Install local pre-commit hooks"
	@echo "  make clean           - Clean up sessions and cache"
	@echo ""
	@echo "  Frontend (React):"
	@echo "  make frontend-install - Install frontend dependencies"
	@echo "  make frontend-test    - Run frontend tests"
	@echo "  make frontend-lint    - Run frontend linter"
	@echo "  make frontend-build   - Build frontend for production"
	@echo "  make frontend-check   - Run all frontend checks (lint, typecheck, test, build)"

install:
	python3 -m venv .venv
	.venv/bin/pip install -e . --ignore-requires-python

bench:
	python scripts/benchmarks/basic_benchmark.py --iterations 50


chat:
	.venv/bin/python -m agentframework.chat $(filter-out $@,$(MAKECMDGOALS))

run:
	.venv/bin/python -m agentframework.cli $(ARGS)

test:
	PYTHONPATH=src uv run pytest --cov=src/agentframework --cov-report=term-missing tests/ -v

lint:
	ruff check src/ tests/

typecheck:
	pyright --pythonpath .venv/bin/python src/

verify:
	uv run pytest tests/ -q
	ruff check src/ tests/
	pyright --pythonpath .venv/bin/python src/

security:
	uv run pip-audit || true
	uv run bandit -r src/ || true

serve-docs:
	NO_MKDOCS_2_WARNING=1 .venv/bin/mkdocs serve

build-docs:
	NO_MKDOCS_2_WARNING=1 .venv/bin/mkdocs build --strict

chats:
	@ls -la ~/.echo-ai/sessions/ 2>/dev/null || echo "No saved chats"

clean:
	rm -rf ~/.echo-ai/sessions/*.db
	rm -rf __pycache__ src/**/__pycache__
	rm -rf site/
	find . -name "*.pyc" -delete

lock: requirements.txt

requirements.txt: pyproject.toml
	uv pip compile pyproject.toml -o requirements.txt


setup-precommit:
	.venv/bin/pre-commit install

# Frontend commands
frontend-install:
	cd frontend && npm install

frontend-test:
	cd frontend && npm run test:run

frontend-lint:
	cd frontend && npm run lint

frontend-typecheck:
	cd frontend && npm run typecheck

frontend-build:
	cd frontend && npm run build

frontend-check:
	cd frontend && npm run lint && npm run typecheck && npm run test:run && npm run build
