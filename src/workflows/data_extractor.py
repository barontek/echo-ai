"""Data Extractor Workflow. Demonstrates rigorous JSON structured extraction chains."""

import json
from typing import Any
from src.agentframework.workflow import WorkflowGraph
from src.workflows._agent_utils import run_with_agent

def get_workflow() -> WorkflowGraph:
    """Return the configured pipeline template."""
    graph = WorkflowGraph()

    async def analyze_text(state: dict[str, Any]) -> dict[str, Any]:
        """Extract loose entities from unstructured text."""
        input_text = state.get("topic", "")
        # Ask the agent to find people, dates, and locations.
        res = await run_with_agent(state,
            f"Analyze the following text. Extract and list all People, Organizations, Locations, and Dates you can find. Text:\n\n{input_text}"
        )
        state["raw_extraction"] = res
        return state

    async def format_json(state: dict[str, Any]) -> dict[str, Any]:
        """Enforce strict structured output matching."""
        raw = state.get("raw_extraction", "")

        schema = {
            "people": ["list of names"],
            "organizations": ["list of organizations"],
            "locations": ["list of places"],
            "dates": ["list of distinct dates/times"]
        }

        # Use underlying structured extraction tool
        res = await run_with_agent(state,
            f"Convert the following extracted entities strictly into the matching standard JSON format:\n{json.dumps(schema)}\n\nEntities: {raw}"
        )

        state["final"] = f"### JSON Extraction Result\n\n```json\n{res}\n```"
        return state

    graph.add_node("analyze_text", analyze_text)
    graph.add_node("format_json", format_json)

    graph.set_entry_point("analyze_text")
    graph.add_edge("analyze_text", "format_json")
    graph.add_edge("format_json", graph.END)

    return graph
