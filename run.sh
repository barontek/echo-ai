#!/usr/bin/env bash
set -e

# Usage:
#   ./run.sh           - Run web UI
#   ./run.sh api       - Run API only
#   ./run.sh chat      - Run CLI chat
#   ./run.sh --docker  - Run in Docker

MODE="${1:-web}"
DOCKER_MODE=0

if [ "$1" == "--docker" ]; then
    DOCKER_MODE=1
    MODE="docker"
fi

if [ $DOCKER_MODE -eq 1 ]; then
    echo "Starting Echo AI in Docker Mode..."
    docker-compose up --build
    exit 0
fi

# Check if .venv exists
if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Running make install..."
    make install
fi

case $MODE in
    web)
        echo "Starting FastAPI Web UI on http://localhost:8080..."
        .venv/bin/python scripts/run_web.py
        ;;
    api)
        echo "Starting FastAPI API on http://localhost:8000..."
        .venv/bin/python scripts/run_api.py --host 0.0.0.0 --port 8000
        ;;
    chat)
        echo "Starting CLI Chat..."
        .venv/bin/python -m agentframework.chat
        ;;
    tui)
        echo "Starting TUI..."
        .venv/bin/python scripts/run_tui.py
        ;;
    *)
        echo "Usage: ./run.sh [web|api|chat|tui|--docker]"
        exit 1
        ;;
esac
