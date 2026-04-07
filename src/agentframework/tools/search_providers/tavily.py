import os
from typing import Any

from .base import BaseSearchProvider


class TavilyProvider(BaseSearchProvider):
    """Tavily search provider."""

    def __init__(self):
        self.api_key = os.environ.get("TAVILY_API_KEY")
        if not self.api_key:
            raise ValueError("TAVILY_API_KEY environment variable not set")

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """
        Search using Tavily.

        Args:
            query: Search query string
            max_results: Max number of results

        Returns:
            List of dicts with {title, url, snippet}
        """
        try:
            from tavily import TavilyClient  # type: ignore[import]

            client = TavilyClient(api_key=self.api_key)
            response = client.search(
                query=query,
                max_results=max_results,
                include_answer=False,
                include_raw_content=False,
                include_images=False,
            )

            results: list[dict[str, Any]] = response.get("results", [])
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", ""),
                }
                for r in results
            ]
        except Exception as e:
            raise RuntimeError(f"Tavily search failed: {e}") from e
