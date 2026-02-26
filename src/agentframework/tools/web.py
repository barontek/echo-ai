"""Web tools for fetching and searching with network restrictions."""

import httpx
from typing import Any

from ..safety import SafetyConfig, SecurityValidator
from . import Tool, ToolResult


class WebFetchTool(Tool):
    """Fetch web page content with network restrictions."""

    def __init__(self, safety_config: SafetyConfig | None = None):
        super().__init__(
            name="web_fetch",
            description="Fetch content from a URL.",
        )
        
        if safety_config:
            self.validator = SecurityValidator(safety_config)
        else:
            self.validator = SecurityValidator(SafetyConfig(allow_network=False))

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch",
                },
            },
            "required": ["url"],
        }

    async def execute(self, url: str, **kwargs) -> ToolResult:
        """Fetch the URL with safety checks."""
        allowed, reason = self.validator.check_network_allowed(url)
        if not allowed:
            return ToolResult(error=f"Network blocked: {reason}")

        if self.validator.requires_approval("web_fetch"):
            approved = self.validator.get_approval("web_fetch", f"fetch: {url}")
            if not approved:
                return ToolResult(error="Web fetch requires approval")

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                verify=False,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                content = response.text[:50000]
                return ToolResult(content=content)
        except httpx.TimeoutException:
            return ToolResult(error="Request timed out")
        except httpx.HTTPStatusError as e:
            return ToolResult(error=f"HTTP error: {e.response.status_code}")
        except Exception as e:
            return ToolResult(error=str(e))


class WebSearchTool(Tool):
    """Search the web with network restrictions."""

    def __init__(self, safety_config: SafetyConfig | None = None):
        super().__init__(
            name="web_search",
            description="Search the web for information.",
        )
        
        if safety_config:
            self.validator = SecurityValidator(safety_config)
        else:
            self.validator = SecurityValidator(SafetyConfig(allow_network=False))

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, **kwargs) -> ToolResult:
        """Search the web with safety checks."""
        if not self.validator.config.allow_network:
            return ToolResult(error="Web search is disabled")

        if self.validator.requires_approval("web_search"):
            approved = self.validator.get_approval("web_search", f"search: {query}")
            if not approved:
                return ToolResult(error="Web search requires approval")

        try:
            from ddgs import DDGS
            ddgs = DDGS()
            results = list(ddgs.text(query, max_results=5))
            
            if not results:
                return ToolResult(content="No results found.")
            
            formatted = []
            for r in results:
                formatted.append(f"- {r['title']}: {r.get('href', '')}\n  {r.get('body', '')[:200]}")
            
            return ToolResult(content="\n\n".join(formatted))
        except Exception as e:
            return ToolResult(error=f"Search failed: {e}")
