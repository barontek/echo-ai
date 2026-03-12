"""Workflow helpers for agent access."""

from typing import Any


async def run_with_agent(state: dict[str, Any], prompt: str, **kwargs: Any) -> str:
    """Run a prompt using an injected agent instance in workflow state."""
    agent = state.get("agent")
    if agent is None:
        raise RuntimeError("Workflow state is missing an 'agent' instance")
    return await agent.run(prompt, **kwargs)
