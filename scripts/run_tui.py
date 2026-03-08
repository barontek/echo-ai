#!/usr/bin/env python3
"""Run the Echo AI interactive dashboard."""
# ruff: noqa: E402

import sys
from pathlib import Path

# Add project root to PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.agentframework.tui import run_dashboard

if __name__ == "__main__":
    run_dashboard()
