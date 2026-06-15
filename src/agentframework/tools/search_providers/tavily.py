import os
from typing import Any

from .base import BaseSearchProvider


class TavilyProvider(BaseSearchProvider):
    """Tavily search provider optimized for news content."""

    def __init__(self):
        self.api_key = os.environ.get("TAVILY_API_KEY")
        if not self.api_key:
            raise ValueError("TAVILY_API_KEY environment variable not set")

    async def search(self, query: str, max_results: int = 20) -> list[dict[str, Any]]:
        """
        Search using Tavily with advanced news settings.

        Args:
            query: Search query string
            max_results: Max number of results

        Returns:
            List of dicts with {title, url, snippet}
        """
        try:
            from tavily import TavilyClient

            client = TavilyClient(api_key=self.api_key)

            for time_range in ("day", "week"):
                response = client.search(
                    query=query,
                    search_depth="advanced",
                    topic="news",
                    time_range=time_range,
                    max_results=max_results,
                    include_answer=False,
                    include_raw_content=False,
                    include_images=False,
                    include_domains=[
                        "reuters.com", "apnews.com", "bbc.com",
                        "theguardian.com", "aljazeera.com",
                        "middleeasteye.net", "euronews.com",
                        "politico.eu", "afp.com",
                    ],
                    exact_match=True,
                    chunks_per_source="auto",
                )

                results: list[dict[str, Any]] = response.get("results", [])
                results = [r for r in results if r.get("score", 0) > 0.2]

                if results:
                    break

            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content") or r.get("snippet", ""),
                }
                for r in results
            ]
        except Exception as e:
            raise RuntimeError(f"Tavily search failed: {e}") from e
