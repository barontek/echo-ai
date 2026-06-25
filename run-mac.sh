#!/usr/bin/env bash
set -euo pipefail

# run-mac.sh — Apple Silicon (M1/M2/M3/M4) run script
#
# Prerequisites (install manually):
#   - Python 3.11+
#   - Node.js 22+
#   - uv (https://docs.astral.sh/uv/#installation)
#   - npm (comes with Node.js)
#
# Optional:
#   - Nix (https://determinate.systems/nix-installer/) — enables the
#     fully-reproducible dev environment from flake.nix
#
# Usage:
#   ./run-mac.sh              - Run frontend + backend (dev)
#   ./run-mac.sh dev          - Run frontend + backend (dev)
#   ./run-mac.sh web          - Run FastAPI backend only
#   ./run-mac.sh api          - Run API only
#   ./run-mac.sh chat         - Run CLI chat
#   ./run-mac.sh tui          - Run TUI

MODE="${1:-dev}"

# ---- Prerequisite checks ----

FAIL=0

if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 not found. Install Python 3.11+ from https://www.python.org/downloads/"
    FAIL=1
fi

if ! command -v node &>/dev/null; then
    echo "[ERROR] node not found. Install Node.js 22+ from https://nodejs.org/"
    FAIL=1
fi

if ! command -v npm &>/dev/null; then
    echo "[ERROR] npm not found. Install Node.js 22+ from https://nodejs.org/"
    FAIL=1
fi

if ! command -v uv &>/dev/null; then
    echo "[ERROR] uv not found. Install from https://docs.astral.sh/uv/#installation"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    FAIL=1
fi

PYTHON="uv run python"

# Check Python version
PY_VER=$($PYTHON --version 2>&1 | awk '{print $2}' | awk -F. '{print $1"."$2}')
PY_MAJOR=${PY_VER%.*}
PY_MINOR=${PY_VER#*.}
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    echo "[ERROR] Python 3.11+ required (found $PY_VER)"
    FAIL=1
fi

if [ $FAIL -ne 0 ]; then
    exit 1
fi

# ---- Apple Silicon tuning ----

ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ]; then
    echo "[mac] Apple Silicon ($ARCH) — setting arm64 build flags"
    export GRPC_PYTHON_BUILD_SYSTEM_OPENSSL=1
    export GRPC_PYTHON_BUILD_SYSTEM_ZLIB=1
fi

# ---- Environment (nix or uv) ----

if [ -n "${IN_NIX_SHELL:-}" ]; then
    echo "[mac] Running inside nix develop shell"
    PYTHON="python"
elif command -v nix &>/dev/null && [ -f flake.nix ]; then
    echo "[mac] Nix available — entering dev shell..."
    exec nix develop --command bash "$0" "$@"
fi

# ---- Dependency sync (via uv) ----

if [ ! -d .venv ]; then
    echo "[mac] Running uv sync to create .venv and install dependencies..."
    uv sync --extra dev --extra otel --extra ui --extra vector-db --extra web-scraping
fi

if [ ! -d frontend/node_modules ]; then
    echo "[mac] Installing frontend dependencies..."
    (cd frontend && npm install)
fi

# ---- Load env vars ----

if [ -f "$HOME/.echo-ai/.env" ]; then
    set -a
    source "$HOME/.echo-ai/.env"
    set +a
elif [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

export PYTHONPATH="$PWD/src"

# ---- Modes ----

case $MODE in
    dev)
        echo "[mac] Starting backend (FastAPI) + frontend (React/Vite)..."
        cleanup() {
            echo ""
            echo "Stopping services..."
            kill $BACKEND_PID 2>/dev/null || true
            kill $FRONTEND_PID 2>/dev/null || true
            echo "Done."
            exit 0
        }
        trap cleanup SIGINT SIGTERM

        echo "  Backend:  http://localhost:8080"
        echo "  Frontend: http://localhost:3000"
        echo ""

        echo "Starting backend..."
        $PYTHON -m src.agentframework.web_api &
        BACKEND_PID=$!
        sleep 2

        echo "Starting frontend..."
        (cd frontend && npm run dev) &
        FRONTEND_PID=$!

        echo "Press Ctrl+C to stop all services"
        wait
        ;;
    web)
        echo "[mac] Starting FastAPI Web UI on http://localhost:8080..."
        $PYTHON -m src.agentframework.web_api
        ;;
    api)
        echo "[mac] Starting FastAPI API on http://localhost:8000..."
        $PYTHON scripts/run_api.py --host 0.0.0.0 --port 8000
        ;;
    chat)
        echo "[mac] Starting CLI Chat..."
        $PYTHON -m src.agentframework.chat
        ;;
    tui)
        echo "[mac] Starting TUI..."
        $PYTHON -m src.agentframework.tui
        ;;
    *)
        echo "Usage: $0 [dev|web|api|chat|tui]"
        exit 1
        ;;
esac
