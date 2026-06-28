"""Code Reviewer Workflow. Demonstrates parallel node execution."""

from typing import Any
from src.agentframework.workflow import WorkflowGraph
from src.workflows._agent_utils import merge_states, run_with_agent

def get_workflow() -> WorkflowGraph:
    """Return the configured pipeline template."""
    graph = WorkflowGraph()

    async def start(state: dict[str, Any]) -> dict[str, Any]:
        """Entry node."""
        state["code_input"] = state.get("topic", "")
        return state

    async def analyze_style(state: dict[str, Any]) -> dict[str, Any]:
        """Parallel Branch A: Style Analysis."""
        code_input = state.get("code_input", "")
        res = await run_with_agent(state,
            f"Analyze the following code strictly for style, formatting, and PEP8/convention compliance. Be brief.\n\n```\n{code_input}\n```"
        )
        state["style_report"] = res
        return state

    async def analyze_bugs(state: dict[str, Any]) -> dict[str, Any]:
        """Parallel Branch B: Bug Analysis."""
        code_input = state.get("code_input", "")
        res = await run_with_agent(state,
            f"Analyze the following code strictly for logical bugs, security flaws, and runtime errors. Be brief.\n\n```\n{code_input}\n```"
        )
        state["bug_report"] = res
        return state

    async def format_report(state: dict[str, Any]) -> dict[str, Any]:
        """Final output formatter."""
        style = state.get("style_report", "No style issues found.")
        bugs = state.get("bug_report", "No runtime bugs found.")

        state["final"] = (
            "### Code Review Report\n\n"
            "**🐛 Logic & Bugs Analysis**\n"
            f"{bugs}\n\n"
            "**💅 Style & Conventions Analysis**\n"
            f"{style}"
        )
        return state

    # Build Graph Topology
    graph.add_node("start", start)
    graph.add_node("analyze_style", analyze_style)
    graph.add_node("analyze_bugs", analyze_bugs)
    graph.add_node("format_report", format_report)

    # Define route map
    graph.set_entry_point("start")

    # Run the two analysis branches in parallel, squash responses through reducer, next node is format_report
    graph.add_parallel_edge(
        source="start",
        targets=["analyze_style", "analyze_bugs"],
        reducer=merge_states,
        next_node="format_report"
    )

    graph.add_edge("format_report", graph.END)

    return graph
