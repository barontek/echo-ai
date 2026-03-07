# Agent Framework Makefile

.PHONY: help install install-dev run chat test lint typecheck verify security bench clean sessions

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
	@echo "  make bench           - Run benchmark harness"
	@echo "  make serve-docs      - Serve MkDocs documentation locally"
	@echo "  make chats           - List saved chats"
	@echo "  make lock            - Generate strict dependencies using uv"
	@echo "  make setup-precommit - Install local pre-commit hooks"
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
	.venv/bin/pytest --cov=src/agentframework --cov-report=term-missing tests/ -v

lint:
	.venv/bin/ruff check src/

typecheck:
	.venv/bin/pyright src/

verify:
	pytest tests/ -q
	ruff check src/ tests/
	pyright src/

security:
	.venv/bin/pip-audit || true
	.venv/bin/bandit -r src/ || true

	python scripts/benchmarks/basic_benchmark.py --iterations 50

serve-docs:
	NO_MKDOCS_2_WARNING=1 .venv/bin/mkdocs serve

build-docs:
	NO_MKDOCS_2_WARNING=1 .venv/bin/mkdocs build --strict

chats:
	@ls -la .agent_sessions/ 2>/dev/null || echo "No saved chats"

clean:
	rm -rf .agent_sessions/*.json
	rm -rf __pycache__ src/**/__pycache__
	rm -rf site/
	find . -name "*.pyc" -delete

lock: requirements.txt requirements-dev.txt

requirements.txt: pyproject.toml
	uv pip compile pyproject.toml -o requirements.txt

requirements-dev.txt: pyproject.toml
	uv pip compile pyproject.toml --extra dev -o requirements-dev.txt

setup-precommit:
	.venv/bin/pre-commit install
