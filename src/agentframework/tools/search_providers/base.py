from typing import Any, Protocol


class BaseSearchProvider(Protocol):
    """Search provider interface."""

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """
        Search the web for information.

        Args:
            query: Search query string
            max_results: Max number of results to return

        Returns:
            List of dicts with keys:
                - title: str - Result title
                - url: str - Result URL
                - snippet: str - Result snippet/description

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        ...  # pragma: no cover
