"""Session CRUD endpoints."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from ..session import DBSessionModel
from ..web_api import (
    AppState,
    SessionRenamePayload,
    create_session_data,
    delete_session_data,
    get_sessions_data,
    get_state,
    load_session_data,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Sessions"])


@router.get("/api/sessions")
async def list_sessions(
    state: Annotated[AppState, Depends(get_state)],
):
    """List all chat sessions.

    Returns sessions sorted by creation date (newest first).
    Each session includes:
    - id: Session identifier
    - title: Auto-generated or user-defined title
    - created_at: Timestamp

    Returns:
        {"sessions": [{"id": "...", "title": "...", "created_at": "..."}, ...]}
    """
    if state.agent and state.agent.session_manager:
        state.agent.session_manager.purge_empty_sessions()
    return get_sessions_data(state)


@router.post("/api/sessions")
async def create_session(
    state: Annotated[AppState, Depends(get_state)],
):
    """Create a new chat session.

    Initializes a fresh session for a new conversation.
    The session ID is generated from the current timestamp (YYYYMMDD_HHMMSS).

    Returns:
        {"session_id": "20260319_143052", "title": null}
    """
    return create_session_data(state)


@router.get("/api/sessions/{session_id}")
async def load_session(
    session_id: str,
    state: Annotated[AppState, Depends(get_state)],
):
    """Load a specific session with its message history.

    Args:
        session_id: The session identifier

    Returns:
        {
            "session_id": "20260319_143052",
            "title": "Weather in Istanbul",
            "messages": [
                {"role": "user", "content": "...", "timestamp": "14:30"},
                {"role": "assistant", "content": "...", "tool_calls": [...], "timestamp": "14:31"}
            ]
        }

    Note:
        Messages are filtered for UI rendering (tool messages removed, thinking extracted)
    """
    return load_session_data(session_id, state)


@router.delete("/api/sessions/{session_id}")
async def delete_session(
    session_id: str,
    state: Annotated[AppState, Depends(get_state)],
):
    """Delete a chat session.

    Permanently removes the session and all its messages from the database.

    Args:
        session_id: The session identifier to delete

    Returns:
        {"status": "ok"}
    """
    return delete_session_data(session_id, state)


@router.post("/api/sessions/rename")
async def rename_session(
    payload: SessionRenamePayload,
    state: Annotated[AppState, Depends(get_state)],
):
    """Rename a session by changing its title.

    Body:
        - session_id: The session to rename
        - new_title: The new title for the session

    Returns:
        {"status": "ok", "session_id": "...", "title": "..."}
    """
    if not (state.agent and state.agent.session_manager):
        raise HTTPException(
            status_code=503,
            detail="Session service is unavailable. Please try again later.",
        )

    with state.agent.session_manager.SessionLocal() as db:
        updated = (
            db.query(DBSessionModel)
            .filter(DBSessionModel.id == payload.session_id)
            .update({"title": payload.new_title})
        )
        if updated == 0:
            raise HTTPException(
                status_code=404,
                detail=f"Session with ID '{payload.session_id}' was not found.",
            )
        db.commit()

    if (
        state.agent.session_manager.current_session
        and state.agent.session_manager.current_session.id == payload.session_id
    ):
        state.agent.session_manager.current_session.title = payload.new_title

    return {
        "status": "ok",
        "session_id": payload.session_id,
        "title": payload.new_title,
    }


@router.get("/api/sessions/{session_id}/export")
async def export_session(
    session_id: str,
    state: Annotated[AppState, Depends(get_state)],
):
    """Export a session to JSON format.

    Args:
        session_id: The session identifier to export

    Returns:
        Session data as JSON dictionary
    """
    if not (state.agent and state.agent.session_manager):
        raise HTTPException(
            status_code=503,
            detail="Session service is unavailable. Please try again later.",
        )

    session_data = state.agent.session_manager.export_session(session_id)
    if session_data is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session with ID '{session_id}' was not found.",
        )

    return session_data


@router.post("/api/sessions/import")
async def import_session(
    request: Request,
    state: Annotated[AppState, Depends(get_state)],
):
    """Import a session from JSON format.

    Body:
        JSON session data (from export endpoint)

    Returns:
        {"status": "ok", "session_id": "..."}
    """
    if not (state.agent and state.agent.session_manager):
        raise HTTPException(
            status_code=503,
            detail="Session service is unavailable. Please try again later.",
        )

    try:
        data = await request.json()
    except Exception as e:
        logger.warning("Invalid JSON in import request: %s", e)
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON in request body.",
        )

    try:
        session = state.agent.session_manager.import_session(data)
        return {"status": "ok", "session_id": session.id}
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )


@router.post("/api/sessions/purge")
async def purge_sessions(
    state: Annotated[AppState, Depends(get_state)],
    days: int = 30,
):
    """Purge old sessions (older than `days` days)."""
    if not (state.agent and state.agent.session_manager):
        raise HTTPException(
            status_code=503,
            detail="Session service is unavailable. Please try again later.",
        )

    count = state.agent.session_manager.purge_sessions(older_than_days=days)
    return {"status": "ok", "purged_count": count}


@router.post("/api/sessions/purge-empty")
async def purge_empty_sessions(
    state: Annotated[AppState, Depends(get_state)],
):
    """Purge sessions that have no user messages (empty sessions)."""
    if not (state.agent and state.agent.session_manager):
        raise HTTPException(
            status_code=503,
            detail="Session service is unavailable. Please try again later.",
        )

    count = state.agent.session_manager.purge_empty_sessions()
    return {"status": "ok", "purged_count": count}
