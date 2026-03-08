"""Workflow Graph Engine for Agentic State Machines."""

from typing import Any, Callable, Coroutine, AsyncGenerator

State = dict[str, Any]
NodeFunc = Callable[[State], Coroutine[Any, Any, State]]


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


class WorkflowGraph:
    """Orchestrates deterministic multi-step state machine execution, contrasting with Agentic ReAct loops."""

    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, list[Edge]] = {}
        self.entry_point: str | None = None
        self.END = "__end__"

    def add_node(self, name: str, func: NodeFunc):
        """Register a new distinct processing node."""
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

    async def run_streaming(
        self, initial_state: State
    ) -> AsyncGenerator[tuple[str, State], None]:
        """Run the graph asynchronously, yielding each active node name and state update."""
        if not self.entry_point:
            raise ValueError("Entry point not set for WorkflowGraph")

        current_node_name = self.entry_point
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
            state = await node.func(state)

            # Find next transition
            edges = self.edges.get(current_node_name, [])
            if not edges:
                break  # Implicit terminal end if no edges exist

            edge = edges[0]
            if callable(edge.condition):
                current_node_name = edge.condition(state)
            else:
                current_node_name = edge.condition

        # Yield the final transition to END state implicitly
        yield self.END, state

    async def compile_and_run(self, initial_state: State) -> State:
        """Synchronously blocks and runs the graph until it reaches the END terminal state."""
        state = initial_state
        async for _, s in self.run_streaming(initial_state):
            state = s
        return state
