#!/usr/bin/env bash
set -e

# Usage:
#   ./run.sh           - Run NiceGUI web UI (recommended)
#   ./run.sh web       - Run FastAPI web UI (legacy)
#   ./run.sh api       - Run API only
#   ./run.sh chat      - Run CLI chat
#   ./run.sh --docker  - Run in Docker

MODE="${1:-nicegui}"
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

# Load environment variables from .env if present
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

case $MODE in
    nicegui)
        echo "Starting NiceGUI Web UI on http://localhost:8080..."
        .venv/bin/python -m src.agentframework.ui.app
        ;;
    web)
        echo "Starting FastAPI Web UI on http://localhost:8080..."
        .venv/bin/python -m src.agentframework.web_api
        ;;
    api)
        echo "Starting FastAPI API on http://localhost:8000..."
        .venv/bin/python scripts/run_api.py --host 0.0.0.0 --port 8000
        ;;
    chat)
        echo "Starting CLI Chat..."
        .venv/bin/python -m src.agentframework.chat
        ;;
    tui)
        echo "Starting TUI..."
        .venv/bin/python -m src.agentframework.tui
        ;;
    *)
        echo "Usage: ./run.sh [nicegui|web|api|chat|tui|--docker]"
        exit 1
        ;;
esac
