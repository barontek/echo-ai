"""Workflow endpoints."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ..config import load_config
from ..constants import DEFAULT_MODEL
from ..web_api import (
    AppState,
    WorkflowRunPayload,
    _create_runtime_agent,
    get_state,
)
from src.workflows import get_workflow, list_workflows

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Workflows"])


@router.get("/api/workflows")
async def workflows_list():
    """List available workflows for UI consumption."""
    return {"workflows": list_workflows()}


@router.post("/api/workflows/run")
async def workflow_run(
    payload: WorkflowRunPayload,
    state: Annotated[AppState, Depends(get_state)],
):
    """Run a selected workflow and return its final output."""
    if state.agent is None:
        cfg = load_config()
        provider = cfg.get("model", {}).get("provider", "ollama")
        model = cfg.get("model", {}).get("name") or DEFAULT_MODEL
        state.agent = _create_runtime_agent(
            provider=provider, model=model
        )

    try:
        workflow = get_workflow(payload.workflow_id)
    except KeyError:
        available = list_workflows()
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{payload.workflow_id}' not found. Available: {available}",
        )

    initial_state = {"topic": payload.topic, "agent": state.agent}
    final_state = await workflow.compile_and_run(initial_state)
    content = final_state.get("final") or final_state.get("result") or str(final_state)

    timestamp = datetime.now().strftime("%H:%M")
    user_content = f"[Workflow: {payload.workflow_id}] {payload.topic}"
    state.message_history.append(
        {"role": "user", "content": user_content, "timestamp": timestamp}
    )
    state.message_history.append(
        {"role": "assistant", "content": content, "timestamp": timestamp}
    )

    return {
        "workflow_id": payload.workflow_id,
        "response": content,
        "timestamp": timestamp,
    }
