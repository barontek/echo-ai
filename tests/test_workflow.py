"""Tests for the Workflow Graph Engine."""

import pytest
from typing import Any
from src.agentframework.workflow import WorkflowGraph

State = dict[str, Any]


@pytest.mark.asyncio
async def test_workflow_streaming():
    """Verify that run_streaming() correctly yields nodes sequentially."""
    graph = WorkflowGraph()

    async def step_one(state: State) -> State:
        state["history"].append("one")
        return state

    async def step_two(state: State) -> State:
        state["history"].append("two")
        return state

    graph.add_node("step_one", step_one)
    graph.add_node("step_two", step_two)
    graph.set_entry_point("step_one")
    graph.add_edge("step_one", "step_two")
    graph.add_edge("step_two", graph.END)

    yielded_nodes = []
    final_state = {}

    async for node, state in graph.run_streaming({"history": []}):
        yielded_nodes.append(node)
        final_state = state

    assert yielded_nodes == ["step_one", "step_two", graph.END]
    assert final_state["history"] == ["one", "two"]


@pytest.mark.asyncio
async def test_workflow_backward_compatibility():
    """Verify that compile_and_run() wrapper matches previous functional sync-like behavior."""
    graph = WorkflowGraph()

    async def single_step(state: State) -> State:
        state["val"] += 1
        return state

    graph.add_node("single", single_step)
    graph.set_entry_point("single")
    graph.add_edge("single", graph.END)

    final_state = await graph.compile_and_run({"val": 0})
    assert final_state["val"] == 1


@pytest.mark.asyncio
async def test_workflow_conditional_routing():
    """Verify dynamic node routing logic."""
    graph = WorkflowGraph()

    async def start(state: State) -> State:
        return state

    async def choice_a(state: State) -> State:
        state["path"] = "A"
        return state

    async def choice_b(state: State) -> State:
        state["path"] = "B"
        return state

    graph.add_node("start", start)
    graph.add_node("choice_a", choice_a)
    graph.add_node("choice_b", choice_b)
    graph.set_entry_point("start")

    def router(state: State) -> str:
        return "choice_a" if state.get("val") == 1 else "choice_b"

    graph.add_conditional_edge("start", router)
    graph.add_edge("choice_a", graph.END)
    graph.add_edge("choice_b", graph.END)

    state_a = await graph.compile_and_run({"val": 1})
    assert state_a["path"] == "A"

    state_b = await graph.compile_and_run({"val": 2})
    assert state_b["path"] == "B"
