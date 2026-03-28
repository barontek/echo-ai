"""Backward-compatible re-export of router.

Deprecated: Import from agentframework.core instead.
"""

from .core.router import SemanticRouter, RouteSelection

__all__ = ["SemanticRouter", "RouteSelection"]
