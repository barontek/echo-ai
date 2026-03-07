#!/usr/bin/env python3
"""Run the Vibe AI Streamlit Web UI.

Usage:
    streamlit run scripts/run_web.py
"""
# ruff: noqa: E402


import sys
from pathlib import Path

# Add project root to PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.agentframework.web_ui import run_app

if __name__ == "__main__":
    run_app()
