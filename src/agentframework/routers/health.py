"""Health check endpoints."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter

from .. import __version__
from ..web_models import get_state

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    """Health check endpoint for container orchestration and load balancers.

    Returns 200 OK if the service is running.
    Use this endpoint for:
    - Kubernetes liveness/readiness probes
    - Load balancer health checks
    - Monitoring systems
    """
    return {
        "status": "healthy",
        "service": "echo-ai",
        "version": __version__,
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/health/detailed")
async def detailed_health_check():
    """Detailed health check with component status.

    Returns detailed status of all components including:
    - LLM provider connectivity
    - Session storage
    - Memory store
    """
    state = get_state()
    components = {
        "service": "healthy",
        "provider": "unknown",
        "sessions": "unknown",
        "memory": "unknown",
    }

    if state.agent:
        components["provider"] = "connected"

    if state.agent and state.agent.session_manager:
        try:
            sessions, total = state.agent.session_manager.list_sessions(limit=1)
            components["sessions"] = f"ok ({total} sessions)"
        except Exception as e:
            components["sessions"] = f"error: {str(e)}"

    if state.agent and state.agent.memory_manager:
        components["memory"] = "ok"

    all_healthy = all(
        v != "error" and not v.startswith("error")
        for v in components.values()
        if v != "unknown"
    )

    return {
        "status": "healthy" if all_healthy else "degraded",
        "service": "echo-ai",
        "version": __version__,
        "components": components,
        "timestamp": datetime.now().isoformat(),
    }
