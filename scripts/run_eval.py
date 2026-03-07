#!/usr/bin/env python3
"""Run the Vibe AI Evaluation Benchmark Suite.

Usage:
    scripts/run_eval.py
"""
# ruff: noqa: E402


import sys
import asyncio
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.agentframework.agent import AgentConfig
from tests.eval.evaluator import evaluate_dataset

async def main():
    # Load the base dataset
    dataset_path = project_root / "tests" / "eval" / "dataset.json"

    # We evaluate the default general-purpose Open Source implementation
    config = AgentConfig(
        provider="ollama",
        model="qwen3:4b-instruct",
        session_enabled=False
    )

    await evaluate_dataset(str(dataset_path), config)

if __name__ == "__main__":
    asyncio.run(main())
