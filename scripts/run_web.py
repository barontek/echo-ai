#!/usr/bin/env python3
"""Run the Echo AI FastAPI Web UI.

Usage:
    python scripts/run_web.py
    # or
    uvicorn src.agentframework.web_api:app --reload --port 8080
"""

import sys
from pathlib import Path


def main() -> None:
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))

    from src.agentframework.web_api import DEFAULT_WEB_PORT, run_server

    run_server(host="0.0.0.0", port=DEFAULT_WEB_PORT)


if __name__ == "__main__":
    main()
