"""Models endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from src.agentframework.web_api import get_models_data

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Models"])


@router.get("/api/models")
async def list_models():
    """List available Ollama models."""
    return await get_models_data()
