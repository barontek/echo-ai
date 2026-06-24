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
        provider_type = (self._limits or {}).get("provider", "brave")
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
                model=model_cfg.get("name", "qwen3.5:latest"),
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
                search_provider.search(query, max_results=10),
                timeout=30.0,
            )
        except Exception as e:
            logger.exception("DeepSearch search failed")
            return ToolResult(error=f"Search failed: {e}")

        if not results:
            return ToolResult(content="No results found.")

        results = results[:10]

        from .web import WebFetchTool
        fetch_tool = WebFetchTool(
            safety_config=self._safety_config,
            limits=self._limits,
        )

        async def fetch(r: dict[str, Any]) -> tuple[str, str, str]:
            result = await fetch_tool.execute(r.get("url", ""))
            content = result.content if not result.error else r.get("snippet", "")
            return r.get("title", ""), r.get("url", ""), content

        semaphore = asyncio.Semaphore(5)

        async def fetch_with_limit(r: dict[str, Any]) -> tuple[str, str, str]:
            async with semaphore:
                return await fetch(r)

        contents = await asyncio.gather(*(fetch_with_limit(r) for r in results))

        def _strip_thinking(text: str) -> str:
            if THINKING_START in text and THINKING_END in text:
                parts = text.split(THINKING_END, 1)
                return parts[1].strip()
            return text.strip()

        async def summarize_batch(batch: list[tuple[str, str, str]]) -> list[str]:
            try:
                sources = "\n\n".join(
                    f"--- Source {j+1} ---\nTitle: {t}\nURL: {u}\nContent:\n{c[:8000]}"
                    for j, (t, u, c) in enumerate(batch)
                )
                response = await provider.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a relevance filter. Given a search query "
                                "and multiple source pages, extract all key details "
                                "from each source and provide a comprehensive summary "
                                "for each. If a source has no relevant information, "
                                "respond with DISCARD for that source. "
                                "Format:\nSource 1: <summary or DISCARD>\nSource 2: ..."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"Query: {query}\n\n{sources}",
                        },
                    ],
                    temperature=0.0,
                )
                result = _strip_thinking(response.content)
                parts: list[str] = []
                for j, (t, u, _) in enumerate(batch):
                    for line in result.split("\n"):
                        if line.strip().startswith(f"Source {j+1}:"):
                            summary = line.split(":", 1)[1].strip()
                            if summary != "DISCARD":
                                parts.append(f"{t}: {u}\n{summary}")
                            break
                return parts
            except Exception:
                return []

        formatted_parts: list[str] = []
        for i in range(0, len(contents), 2):
            batch = contents[i:i+2]
            formatted_parts.extend(await summarize_batch(batch))

        if not formatted_parts:
            return ToolResult(content="No relevant results found.")

        return ToolResult(content="\n".join(formatted_parts))
