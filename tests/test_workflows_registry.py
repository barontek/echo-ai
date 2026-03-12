"""Tests for workflow registry loading."""

import pytest

from src.agentframework.workflow import WorkflowGraph
from src.workflows import get_workflow, list_workflows


def test_list_workflows_contains_expected_items():
    workflows = list_workflows()

    assert workflows
    ids = {workflow["id"] for workflow in workflows}
    assert "research_and_summarize" in ids
    assert "code_reviewer" in ids


def test_get_workflow_returns_graph():
    graph = get_workflow("research_and_summarize")

    assert isinstance(graph, WorkflowGraph)


def test_get_workflow_unknown_raises_key_error():
    with pytest.raises(KeyError):
        get_workflow("does_not_exist")
