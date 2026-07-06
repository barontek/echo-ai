"""Workflow endpoints."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ..config import load_config
from ..constants import DEFAULT_MODEL
from ..web_models import (
    AppState,
    WorkflowRunPayload,
    get_state,
)
from workflows import get_workflow, list_workflows

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
    from .. import web_api as _web_api
    if state.agent is None:
        cfg = load_config()
        provider = cfg.get("model", {}).get("provider", "ollama")
        model = cfg.get("model", {}).get("name") or DEFAULT_MODEL
        state.agent = _web_api._create_runtime_agent(
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
    content = (
        final_state["final"] if "final" in final_state and final_state["final"] is not None
        else final_state["result"] if "result" in final_state and final_state["result"] is not None
        else str(final_state)
    )

    timestamp = datetime.now().strftime("%H:%M")
    user_content = f"[Workflow: {payload.workflow_id}] {payload.topic}"
    state.message_history.append(
        {"role": "user", "content": user_content, "timestamp": timestamp}
    )
    state.message_history.append(
        {"role": "assistant", "content": content, "timestamp": timestamp}
    )

    if state.agent and hasattr(state.agent, 'session_manager') and state.agent.session_manager:
        if state.agent.session_manager.current_session:
            state.agent.save_session()

    return {
        "workflow_id": payload.workflow_id,
        "response": content,
        "timestamp": timestamp,
    }
