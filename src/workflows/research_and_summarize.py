"""Research & Summarize Workflow Template."""

import asyncio
import os
from typing import Any
from src.agentframework.workflow import WorkflowGraph
from src.workflows._agent_utils import run_with_agent

WORKFLOW_RESEARCH_DELAY = float(os.environ.get("WORKFLOW_RESEARCH_DELAY", "0"))
WORKFLOW_FORMAT_DELAY = float(os.environ.get("WORKFLOW_FORMAT_DELAY", "0"))


def get_workflow() -> WorkflowGraph:
    """Return the configured pipeline template."""
    graph = WorkflowGraph()

    async def node_research(state: dict[str, Any]) -> dict[str, Any]:
        if WORKFLOW_RESEARCH_DELAY > 0:
            await asyncio.sleep(WORKFLOW_RESEARCH_DELAY)
        res = await run_with_agent(
            state,
            f"Write a comprehensive 2-sentence summary detailing: {state.get('topic', 'N/A')}",
        )
        state["research_result"] = res
        return state

    async def node_format(state: dict[str, Any]) -> dict[str, Any]:
        if WORKFLOW_FORMAT_DELAY > 0:
            await asyncio.sleep(WORKFLOW_FORMAT_DELAY)
        raw = state.get("research_result", "")
        state["final"] = (
            f"### Executive Summary\n\n{raw}\n\n*Compiled by Echo AI Orchestrator*"
        )
        return state

    graph.add_node("research", node_research)
    graph.add_node("format", node_format)

    graph.set_entry_point("research")
    graph.add_edge("research", "format")
    graph.add_edge("format", graph.END)

    return graph
