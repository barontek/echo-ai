"""Blog Post Creator Workflow. Demonstrates sequential multi-step generative dependency chains."""

from typing import Any
from src.agentframework.workflow import WorkflowGraph
from src.workflows._agent_utils import run_with_agent


def get_workflow() -> WorkflowGraph:
    """Return the configured pipeline template."""
    graph = WorkflowGraph()

    async def generate_outline(state: dict[str, Any]) -> dict[str, Any]:
        """Node 1: Plan the post architecture."""
        state["topic"] = state.get("topic", "The Future of AI Automation")
        res = await run_with_agent(state, 
            f"Write a 3-bullet point outline for a blog post about {state['topic']}."
        )
        state["outline"] = res
        return state

    async def draft_post(state: dict[str, Any]) -> dict[str, Any]:
        """Node 2: Expand the outline into body content."""
        res = await run_with_agent(state, 
            f"Draft a short blog post using the following outline as a rigid guide:\n\n{state['outline']}"
        )
        state["draft"] = res
        return state

    async def seo_optimize(state: dict[str, Any]) -> dict[str, Any]:
        """Node 3: Analyze and editorialize the generated draft."""
        res = await run_with_agent(state, 
            f"You are an SEO expert. Refine and optimize this draft. Add a catchy H1 Title and inject high-value keywords seamlessly.\n\nDraft:\n{state['draft']}"
        )
        state["final"] = f"### Final Published Post\n\n{res}"
        return state

    graph.add_node("generate_outline", generate_outline)
    graph.add_node("draft_post", draft_post)
    graph.add_node("seo_optimize", seo_optimize)
    
    graph.set_entry_point("generate_outline")
    graph.add_edge("generate_outline", "draft_post")
    graph.add_edge("draft_post", "seo_optimize")
    graph.add_edge("seo_optimize", graph.END)
    
    return graph
