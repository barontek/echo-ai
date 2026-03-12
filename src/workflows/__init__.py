"""Workflow definitions registry."""

from importlib import import_module
from typing import Any

from src.agentframework.workflow import WorkflowGraph

WORKFLOW_REGISTRY: dict[str, dict[str, str]] = {
    "research_and_summarize": {
        "title": "Research & Summarize",
        "description": "Quick research-backed summary for a topic.",
        "module": "src.workflows.research_and_summarize",
    },
    "newsletter_generator": {
        "title": "Newsletter Generator",
        "description": "Generate a complete newsletter draft with intro/body/conclusion.",
        "module": "src.workflows.newsletter_generator",
    },
    "blog_post_creator": {
        "title": "Blog Post Creator",
        "description": "Create a blog post from outline to SEO-optimized final draft.",
        "module": "src.workflows.blog_post_creator",
    },
    "debate_simulator": {
        "title": "Debate Simulator",
        "description": "Generate pro/con arguments and an impartial verdict.",
        "module": "src.workflows.debate_simulator",
    },
    "code_reviewer": {
        "title": "Code Reviewer",
        "description": "Review code for bugs and style issues in parallel.",
        "module": "src.workflows.code_reviewer",
    },
    "data_extractor": {
        "title": "Data Extractor",
        "description": "Extract structured entities from unstructured text.",
        "module": "src.workflows.data_extractor",
    },
}


def list_workflows() -> list[dict[str, str]]:
    """Return available workflow metadata for UI/API usage."""
    return [
        {
            "id": workflow_id,
            "title": config["title"],
            "description": config["description"],
        }
        for workflow_id, config in WORKFLOW_REGISTRY.items()
    ]


def get_workflow(workflow_id: str) -> WorkflowGraph:
    """Load and build a workflow graph by id."""
    config = WORKFLOW_REGISTRY.get(workflow_id)
    if not config:
        raise KeyError(f"Unknown workflow id: {workflow_id}")

    module = import_module(config["module"])
    workflow_factory: Any = getattr(module, "get_workflow", None)
    if workflow_factory is None:
        raise RuntimeError(f"Workflow module {config['module']} has no get_workflow()")

    graph = workflow_factory()
    if not isinstance(graph, WorkflowGraph):
        raise TypeError(f"Workflow {workflow_id} did not return a WorkflowGraph")

    return graph
