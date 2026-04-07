from .base import BaseSearchProvider


class DuckDuckGoProvider(BaseSearchProvider):
    """DuckDuckGo search provider."""

    def __init__(self):
        pass

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        """
        Search using DuckDuckGo.

        Args:
            query: Search query string
            max_results: Max number of results

        Returns:
            List of dicts with {title, url, snippet}
        """
        try:
            from ddgs import DDGS

            ddgs = DDGS()
            results = list(ddgs.text(query, max_results=max_results))

            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                }
                for r in results
            ]
        except Exception as e:
            raise RuntimeError(f"DuckDuckGo search failed: {e}") from e
