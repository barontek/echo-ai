"""Models endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Models"])


@router.get("/api/models")
async def list_models(provider: str = Query("ollama", description="Provider to list models for")):
    """List available models for the given provider."""
    from .. import web_api as _web_api
    return await _web_api.get_models_data(provider=provider)
