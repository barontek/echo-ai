import json
import os
from typing import Any

import httpx

from .base import BaseSearchProvider

_DEFAULT_TAVILY_DOMAINS = [
    "reuters.com", "apnews.com", "bbc.com",
    "theguardian.com", "aljazeera.com",
    "middleeasteye.net", "euronews.com",
    "politico.eu", "afp.com",
]


def _get_tavily_domains() -> list[str]:
    raw = os.environ.get("TAVILY_INCLUDE_DOMAINS", "")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except (ValueError, SyntaxError):
            pass
    return _DEFAULT_TAVILY_DOMAINS


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
            async with httpx.AsyncClient(timeout=30.0) as client:
                for time_range in ("day", "week"):
                    payload = {
                        "api_key": self.api_key,
                        "query": query,
                        "search_depth": "advanced",
                        "topic": "news",
                        "time_range": time_range,
                        "max_results": max_results,
                        "include_answer": False,
                        "include_raw_content": False,
                        "include_images": False,
                        "include_domains": _get_tavily_domains(),
                    }
                    resp = await client.post(
                        "https://api.tavily.com/search",
                        json=payload,
                    )
                    resp.raise_for_status()
                    response = resp.json()

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
