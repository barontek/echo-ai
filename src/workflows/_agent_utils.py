"""Workflow helpers for agent access."""

from typing import Any


async def run_with_agent(state: dict[str, Any], prompt: str, **kwargs: Any) -> str:
    """Run a prompt using an injected agent instance in workflow state."""
    agent = state.get("agent")
    if agent is None:
        raise RuntimeError("Workflow state is missing an 'agent' instance")

    system_injection = kwargs.pop("system_injection", None)
    if system_injection:
        agent.add_system_message(system_injection)

    if kwargs:
        import logging
        logging.getLogger(__name__).warning(
            "Ignoring unexpected kwargs passed to run_with_agent: %s", kwargs
        )

    return await agent.run(prompt)


def merge_states(states: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge multiple parallel workflow states into one."""
    if not states:
        return {}
    merged = states[0].copy()
    for s in states[1:]:
        merged.update(s)
    return merged
