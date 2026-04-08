"""Backward-compatible re-export of router.

Deprecated: Import from agentframework.core instead.
"""

import warnings

from .core.router import SemanticRouter, RouteSelection

warnings.warn(
    "Importing from 'agentframework.router' is deprecated. "
    "Import from 'agentframework.core' instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["SemanticRouter", "RouteSelection"]
