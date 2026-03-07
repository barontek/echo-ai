#!/usr/bin/env bash
set -e

# Usage: ./run.sh [--docker]

DOCKER_MODE=0

if [ "$1" == "--docker" ]; then
    DOCKER_MODE=1
fi

if [ $DOCKER_MODE -eq 1 ]; then
    echo "Starting Vibe AI Enterprise Cluster in Docker Mode..."
    docker-compose up --build
else
    echo "Starting Vibe AI Locally..."

    # Check if .venv exists
    if [ ! -d ".venv" ]; then
        echo "Virtual environment not found. Please run 'uv sync' first."
        exit 1
    fi

    # Start the API server in the background
    echo "Starting FastAPI Server on port 8000..."
    .venv/bin/python scripts/run_api.py --host 0.0.0.0 --port 8000 &
    API_PID=$!

    # Trap SIGINT to ensure we clean up the background API server on Ctrl+C
    trap "echo 'Shutting down servers...'; kill $API_PID; exit 0" SIGINT SIGTERM

    # Wait for API to boot
    sleep 2

    # Start Streamlit UI in the foreground
    echo "Starting Streamlit UI on port 8501..."
    .venv/bin/streamlit run scripts/run_web.py
fi
