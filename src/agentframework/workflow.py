"""Workflow Graph Engine for Agentic State Machines."""

import asyncio
from typing import Any, Callable, Coroutine, AsyncGenerator, Union

State = dict[str, Any]
NodeFunc = Callable[[State], Coroutine[Any, Any, State]]

class Interrupt(Exception):
    """Signal to pause workflow execution and return control to the UI."""
    pass


class Node:
    """A node inside the workflow graph representing an executable step."""

    def __init__(self, name: str, func: NodeFunc):
        self.name = name
        self.func = func


class Edge:
    """A directed edge transitioning from one node to another."""

    def __init__(self, source: str, condition: Callable[[State], str] | str):
        # Condition can return the name of the next node, or just be a static target string
        self.source = source
        self.condition = condition


class ParallelEdge:
    """A directed edge transitioning to multiple parallel nodes."""

    def __init__(self, source: str, targets: list[str], reducer: Callable[[list[State]], State], next_node: str):
        self.source = source
        self.targets = targets
        self.reducer = reducer
        self.next_node = next_node


class WorkflowGraph:
    """Orchestrates deterministic multi-step state machine execution, contrasting with Agentic ReAct loops."""

    def __init__(self, checkpoint_manager: Any = None, workflow_id: str | None = None):
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, list[Union[Edge, ParallelEdge]]] = {}
        self.entry_point: str | None = None
        self.END = "__end__"
        self.checkpoint_manager = checkpoint_manager
        self.workflow_id = workflow_id

    def add_node(self, name: str, func: Union[NodeFunc, "WorkflowGraph"]):
        """Register a new distinct processing node or nested sub-graph."""
        if isinstance(func, WorkflowGraph):
            async def _subgraph_wrapper(state: State) -> State:
                return await func.compile_and_run(state)
            self.nodes[name] = Node(name, _subgraph_wrapper)
        else:
            self.nodes[name] = Node(name, func)
        self.edges[name] = []

    def set_entry_point(self, name: str):
        """Define the node where the graph begins execution."""
        self.entry_point = name

    def add_edge(self, source: str, target: str):
        """Add a rigid 1-to-1 deterministic transition edge."""
        self.edges[source].append(Edge(source, target))

    def add_conditional_edge(self, source: str, condition: Callable[[State], str]):
        """Add a dynamic routing edge calculated against the payload state."""
        self.edges[source].append(Edge(source, condition))

    def add_parallel_edge(self, source: str, targets: list[str], reducer: Callable[[list[State]], State], next_node: str):
        """Add a parallel execution route handling multiple nodes simultaneously cleanly resolving to a next node."""
        self.edges[source].append(ParallelEdge(source, targets, reducer, next_node))

    async def run_streaming(
        self, initial_state: State, resume_from: str | None = None
    ) -> AsyncGenerator[tuple[str, State], Any]:
        """Run the graph asynchronously, yielding each active node name and state update."""
        if not self.entry_point and not resume_from:
            raise ValueError("Entry point not set for WorkflowGraph")

        current_node_name: str = resume_from or self.entry_point or ""
        state = initial_state.copy()

        # Hard cap to prevent infinite recursive graphs
        iteration = 0
        max_iterations = 100

        while current_node_name != self.END and iteration < max_iterations:
            iteration += 1
            if current_node_name not in self.nodes:
                raise ValueError(f"Node {current_node_name} not found in graph")

            # Yield the node we are about to execute
            yield current_node_name, state

            node = self.nodes[current_node_name]

            # Wait for execution payload to return manipulated state
            try:
                state = await node.func(state)
            except Interrupt:
                yield "__INTERRUPT__", state
                break

            # Snapshot state for persistence tracking if configured
            if self.checkpoint_manager and self.workflow_id:
                if hasattr(self.checkpoint_manager, "save_checkpoint"):
                    self.checkpoint_manager.save_checkpoint(self.workflow_id, current_node_name, state)

            # Find next transition
            edges = self.edges.get(current_node_name, [])
            if not edges:
                break  # Implicit terminal end if no edges exist

            edge = edges[0]

            if isinstance(edge, ParallelEdge):
                # Execute targets concurrently
                coroutines = []
                # Make isolated state contexts per node branch
                for tgt in edge.targets:
                    if tgt not in self.nodes:
                        raise ValueError(f"Parallel target '{tgt}' not mapped to node list")
                    coroutines.append(self.nodes[tgt].func(state.copy()))

                try:
                    results = await asyncio.gather(*coroutines)
                except Interrupt:
                    yield "__INTERRUPT__", state
                    break

                state = edge.reducer(list(results))
                current_node_name = edge.next_node
            elif callable(edge.condition):
                current_node_name = edge.condition(state)
            else:
                current_node_name = edge.condition

        if current_node_name == self.END or iteration >= max_iterations:
            yield self.END, state

    def to_mermaid(self) -> str:
        """Generate a declarative Mermaid flowchart representing the static map logic."""
        lines = ["stateDiagram-v2"]
        if self.entry_point:
            lines.append(f"    [*] --> {self.entry_point}")

        for source, edges in self.edges.items():
            for edge in edges:
                if isinstance(edge, ParallelEdge):
                    for target in edge.targets:
                        lines.append(f"    {source} --> {target} : Parallel Start")
                    for target in edge.targets:
                        lines.append(f"    {target} --> {edge.next_node} : Parallel Reduce")
                else:
                    target = edge.condition if isinstance(edge.condition, str) else "DynamicRoute"
                    lines.append(f"    {source} --> {target}")

        lines.append(f"    {self.END} --> [*]")
        return "\n".join(lines)

    async def compile_and_run(self, initial_state: State) -> State:
        """Synchronously blocks and runs the graph until it reaches the END terminal state."""
        state = initial_state
        async for _, s in self.run_streaming(initial_state):
            state = s
        return state
