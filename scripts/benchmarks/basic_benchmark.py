"""Basic benchmark harness for latency and throughput smoke checks."""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time

from agentframework.agent import Agent, AgentConfig
from agentframework.providers import LLMProvider, LLMResponse


class FastMockProvider(LLMProvider):
    async def chat(self, messages, tools=None, temperature=0.3):
        return LLMResponse(content="ok")


async def run_once(agent: Agent, prompt: str) -> float:
    start = time.perf_counter()
    await agent.run(prompt)
    return time.perf_counter() - start


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run basic local latency benchmark")
    parser.add_argument("--iterations", type=int, default=25)
    parser.add_argument("--prompt", default="benchmark prompt")
    args = parser.parse_args()

    provider = FastMockProvider()
    agent = Agent(AgentConfig(session_enabled=False), provider)

    timings = []
    for _ in range(args.iterations):
        timings.append(await run_once(agent, args.prompt))

    print(f"iterations={args.iterations}")
    print(f"avg_ms={statistics.mean(timings) * 1000:.2f}")
    print(f"p95_ms={statistics.quantiles(timings, n=20)[18] * 1000:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
