#!/usr/bin/env python3
"""Run the Echo AI FastAPI Web UI.

Usage:
    python scripts/run_web.py
    # or
    uvicorn src.agentframework.web_api:app --reload --port 8501
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.agentframework.web_api import run_server

if __name__ == "__main__":
    run_server(host="0.0.0.0", port=8080)
