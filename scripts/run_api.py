#!/usr/bin/env python3
"""Run the Echo AI FastAPI server.

Usage:
    scripts/run_api.py [--host HOST] [--port PORT]
"""
# ruff: noqa: E402


import sys
import argparse
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import uvicorn

def main():
    parser = argparse.ArgumentParser(description="Run Echo AI API Server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host interface to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    args = parser.parse_args()

    # Pass the import string so uvicorn can handle auto-reloading if needed
    uvicorn.run("src.agentframework.api:app", host=args.host, port=args.port, reload=True)

if __name__ == "__main__":
    main()
