"""Debate Simulator Workflow. Demonstrates adversarial multi-persona parallel simulation."""

from typing import Any
from src.agentframework.workflow import WorkflowGraph
from src.workflows._agent_utils import merge_states, run_with_agent


def get_workflow() -> WorkflowGraph:
    """Return the configured pipeline template."""
    graph = WorkflowGraph()

    async def start(state: dict[str, Any]) -> dict[str, Any]:
        """Initialize debate variables."""
        state["topic"] = state.get("topic", "Should humanity build AGI?")
        return state

    async def argue_pro(state: dict[str, Any]) -> dict[str, Any]:
        """Parallel Branch: Pro-argument persona."""
        sys_prompt = "You are a staunch advocate supporting the topic. You must fiercely argue in favor of it."
        # Run explicitly with system message overriding standard behavior
        res = await run_with_agent(state,
            f"Construct a compelling 3-sentence argument in FAVOR of this topic: {state['topic']}",
            system_injection=sys_prompt,
        )
        state["pro_argument"] = res
        return state

    async def argue_con(state: dict[str, Any]) -> dict[str, Any]:
        """Parallel Branch: Anti-argument persona."""
        sys_prompt = "You are a staunch critic opposing the topic. You must fiercely argue against it."
        res = await run_with_agent(state,
            f"Construct a compelling 3-sentence argument AGAINST this topic: {state['topic']}",
            system_injection=sys_prompt,
        )
        state["con_argument"] = res
        return state

    async def judge(state: dict[str, Any]) -> dict[str, Any]:
        """Sequential Node: Impartial arbiter evaluates arguments."""
        sys_prompt = "You are an impartial Supreme Court Judge. Review both arguments and synthesize a logical, objective conclusion."
        res = await run_with_agent(state,
            f"Topic: {state['topic']}\n\n"
            f"Pro Argument: {state['pro_argument']}\n\n"
            f"Con Argument: {state['con_argument']}\n\n"
            "Deliver your final impartial verdict.",
            system_injection=sys_prompt,
        )

        state["final"] = (
            f"### Debate Simulation: {state['topic']}\n\n"
            f"**PRO Argument:**\n{state['pro_argument']}\n\n"
            f"**CON Argument:**\n{state['con_argument']}\n\n"
            f"---\n\n"
            f"**The Verdict:**\n{res}"
        )
        return state

    graph.add_node("start", start)
    graph.add_node("argue_pro", argue_pro)
    graph.add_node("argue_con", argue_con)
    graph.add_node("judge", judge)

    graph.set_entry_point("start")

    graph.add_parallel_edge(
        source="start",
        targets=["argue_pro", "argue_con"],
        reducer=merge_states,
        next_node="judge",
    )

    graph.add_edge("judge", graph.END)

    return graph
