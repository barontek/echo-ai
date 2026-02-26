# Agent Framework Makefile

.PHONY: help install run chat test clean sessions

help:
	@echo "Agent Framework - Available commands:"
	@echo ""
	@echo "  make install          - Install dependencies"
	@echo "  make chat            - Start chat mode (continuous conversation)"
	@echo "  make chat LOAD=name  - Load and resume a saved chat"
	@echo "  make run 'task'      - Run single task"
	@echo "  make test            - Run basic test"
	@echo "  make chats           - List saved chats"
	@echo "  make clean           - Clean up sessions and cache"

install:
	python3 -m venv .venv
	.venv/bin/pip install -e .

chat:
	.venv/bin/python -m agentframework.chat $(filter-out $@,$(MAKECMDGOALS))

run:
	.venv/bin/python -m agentframework.cli $(ARGS)

test:
	.venv/bin/python -m agentframework.cli "what is 2+2"

chats:
	@ls -la .agent_sessions/ 2>/dev/null || echo "No saved chats"

clean:
	rm -rf .agent_sessions/*.json
	rm -rf __pycache__ src/**/__pycache__
	find . -name "*.pyc" -delete
