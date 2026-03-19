"""Tests for the Workflow Graph Engine."""

import asyncio
import pytest
from typing import Any
from src.agentframework.workflow import WorkflowGraph, Interrupt

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

@pytest.mark.asyncio
async def test_workflow_parallel_edge():
    """Verify that add_parallel_edge() successfully gathers targets concurrently and reduces."""
    graph = WorkflowGraph()

    async def start(state: State) -> State:
        state["val"] = 1
        return state

    async def branch_a(state: State) -> State:
        await asyncio.sleep(0.01)
        state["a_done"] = True
        return state

    async def branch_b(state: State) -> State:
        state["b_done"] = True
        return state

    def reducer(states: list[State]) -> State:
        merged = states[0].copy()
        for s in states[1:]:
            merged.update(s)
        merged["reduced"] = True
        return merged

    graph.add_node("start", start)
    graph.add_node("branch_a", branch_a)
    graph.add_node("branch_b", branch_b)

    graph.set_entry_point("start")
    graph.add_parallel_edge("start", ["branch_a", "branch_b"], reducer, graph.END)

    final_state = await graph.compile_and_run({})
    assert final_state["a_done"] is True
    assert final_state["b_done"] is True
    assert final_state["reduced"] is True

@pytest.mark.asyncio
async def test_workflow_interrupt_and_resume():
    """Verify that __INTERRUPT__ exits the generator safely and resume_from picks up from the state."""
    graph = WorkflowGraph()

    async def step_one(state: State) -> State:
        state["val"] = 1
        return state

    async def step_interrupt(state: State) -> State:
        if not state.get("approved"):
            raise Interrupt()
        state["val"] = 2
        return state

    graph.add_node("step_one", step_one)
    graph.add_node("step_interrupt", step_interrupt)

    graph.set_entry_point("step_one")
    graph.add_edge("step_one", "step_interrupt")
    graph.add_edge("step_interrupt", graph.END)

    yielded = []
    final_state = {}
    async for node, state in graph.run_streaming({}):
        yielded.append(node)
        final_state = state

    assert yielded == ["step_one", "step_interrupt", "__INTERRUPT__"]
    assert final_state["val"] == 1

    # User approves
    final_state["approved"] = True

    # Resume
    resume_yielded = []
    resume_state = {}
    async for node, state in graph.run_streaming(final_state, resume_from="step_interrupt"):
        resume_yielded.append(node)
        resume_state = state

    assert resume_yielded == ["step_interrupt", graph.END]
    assert resume_state["val"] == 2

@pytest.mark.asyncio
async def test_workflow_nested_subgraph():
    """Verify that passing a WorkflowGraph instance as a NodeFunc parses transparently."""
    parent = WorkflowGraph()
    child = WorkflowGraph()

    async def child_start(state: State) -> State:
        state["child_touched"] = True
        return state

    child.add_node("child_start", child_start)
    child.set_entry_point("child_start")
    child.add_edge("child_start", child.END)

    async def parent_start(state: State) -> State:
        state["parent_touched"] = True
        return state

    parent.add_node("parent_start", parent_start)
    parent.add_node("child_subgraph", child)
    parent.set_entry_point("parent_start")
    parent.add_edge("parent_start", "child_subgraph")
    parent.add_edge("child_subgraph", parent.END)

    final_state = await parent.compile_and_run({})
    assert final_state["parent_touched"] is True
    assert final_state["child_touched"] is True
