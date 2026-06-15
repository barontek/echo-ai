"""Deep search tool that searches, fetches, and summarizes results."""

import asyncio
import logging
from typing import Any

from pydantic import BaseModel

from . import Tool, ToolResult
from ..constants import THINKING_END, THINKING_START

logger = logging.getLogger(__name__)


class DeepSearchParams(BaseModel):
    query: str


class DeepSearchTool(Tool):
    """Tool that searches the web, fetches each result, and summarizes
    relevant content using the LLM, returning only filtered summaries."""

    parameters_model = DeepSearchParams

    def __init__(
        self,
        provider: Any = None,
        safety_config: Any = None,
        limits: dict | None = None,
    ):
        super().__init__(
            name="deep_search",
            description=(
                "Deep search that searches the web, fetches each result, and uses "
                "AI to extract and summarize information relevant to the query. "
                "Returns concise, filtered summaries."
            ),
        )
        self.provider = provider
        self._safety_config = safety_config
        self._limits = limits

    def _get_search_provider(self):
        provider_type = (self._limits or {}).get("provider", "duckduckgo")
        from .search_providers import get_search_provider
        return get_search_provider(provider_type)

    def _get_provider(self):
        if self.provider is None:
            from ..providers import get_provider
            from ..config import load_config
            config = load_config()
            model_cfg = config.get("model", {})
            self.provider = get_provider(
                name=model_cfg.get("provider", "ollama"),
                model=model_cfg.get("name", "qwen3:4b-instruct"),
                base_url=model_cfg.get("base_url"),
                timeout=model_cfg.get("timeout", 60),
                num_ctx=model_cfg.get("num_ctx"),
            )
        return self.provider

    async def execute(
        self, query: str, **kwargs: Any
    ) -> ToolResult:
        provider = self._get_provider()

        try:
            search_provider = self._get_search_provider()
            results = await asyncio.wait_for(
                search_provider.search(query, max_results=5),
                timeout=30.0,
            )
        except Exception as e:
            logger.exception("DeepSearch search failed")
            return ToolResult(error=f"Search failed: {e}")

        if not results:
            return ToolResult(content="No results found.")

        results = results[:5]
        fetch_tool = None

        async def fetch(r: dict[str, Any]) -> str:
            nonlocal fetch_tool
            if fetch_tool is None:
                from .web import WebFetchTool
                fetch_tool = WebFetchTool(
                    safety_config=self._safety_config,
                    limits=self._limits,
                )
            result = await fetch_tool.execute(r.get("url", ""))
            if result.error:
                return r.get("snippet", "")
            return result.content

        contents: list[Any] = []
        for r in results:
            contents.append(await fetch(r))

        def _strip_thinking(text: str) -> str:
            if THINKING_START in text and THINKING_END in text:
                parts = text.split(THINKING_END, 1)
                return parts[1].strip()
            return text.strip()

        async def summarize(content: str) -> str:
            if isinstance(content, Exception):
                return "DISCARD"
            try:
                response = await provider.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a relevance filter. Given a search query "
                                "and page content, extract all key details and "
                                "provide a comprehensive summary of the information "
                                "relevant to the query. If the page has no relevant "
                                "information, respond with exactly: DISCARD"
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Query: {query}\n\nContent:\n{content[:8000]}"
                            ),
                        },
                    ],
                    temperature=0.0,
                )
                return _strip_thinking(response.content)
            except Exception:
                return "DISCARD"

        summaries: list[Any] = []
        for c in contents:
            summaries.append(await summarize(c))

        relevant = [
            s for s in summaries
            if isinstance(s, str) and s.strip() != "DISCARD"
        ]

        if not relevant:
            return ToolResult(content="No relevant results found.")

        formatted = "\n".join(f"{i+1}. {s}" for i, s in enumerate(relevant))
        return ToolResult(content=formatted)
