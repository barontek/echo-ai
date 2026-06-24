from typing import Any

from .base import BaseSearchProvider
from .brave import BraveSearchProvider
from .tavily import TavilyProvider


PROVIDERS: dict[str, type[BaseSearchProvider]] = {
    "brave": BraveSearchProvider,
    "tavily": TavilyProvider,
}


def get_search_provider(
    provider_type: str = "brave", **kwargs: Any
) -> BaseSearchProvider:
    """
    Factory to get a search provider by name.

    Args:
        provider_type: Provider name ("brave", "duckduckgo", or "tavily")
        **kwargs: Additional provider-specific config

    Returns:
        BaseSearchProvider instance

    Raises:
        ValueError: If provider_type is unknown
    """
    if provider_type not in PROVIDERS:
        raise ValueError(
            f"Unknown search provider: {provider_type}. "
            f"Available: {list(PROVIDERS.keys())}"
        )
    return PROVIDERS[provider_type](**kwargs)


__all__ = ["BaseSearchProvider", "get_search_provider", "PROVIDERS"]
