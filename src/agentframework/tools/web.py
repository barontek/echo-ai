"""Web tools for fetching and searching with network restrictions."""

import asyncio
from bs4 import BeautifulSoup
from pydantic import BaseModel
import markdownify
try:
    from crawl4ai import AsyncWebCrawler
except ImportError:  # pragma: no cover - optional runtime dependency
    AsyncWebCrawler = None

from ..safety import SafetyConfig, SecurityValidator
from . import Tool, ToolResult


def html_to_markdown(html: str, max_length: int = 10000) -> str:
    """Parse HTML and extract readable markdown using markdownify."""
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Remove script, style, nav, header, footer elements
        for tag in soup(
            ["script", "style", "nav", "header", "footer", "aside", "iframe", "noscript"]
        ):
            tag.decompose()

        # Get the main content area if available, otherwise body
        main = soup.find("main") or soup.find("article") or soup.find("body") or soup

        # Convert to Markdown
        md = markdownify.markdownify(
            str(main),
            heading_style="ATX",
            strip=["script", "style"],
        )

        # Clean up whitespace
        lines = [line.strip() for line in md.split("\n")]
        cleaned_lines = []
        consecutive_empty = 0
        for line in lines:
            if not line:
                consecutive_empty += 1
                if consecutive_empty <= 1:
                    cleaned_lines.append("")
            else:
                consecutive_empty = 0
                cleaned_lines.append(line)

        text = "\n".join(cleaned_lines).strip()

        # Truncate to max length
        if len(text) > max_length:
            text = text[:max_length] + "\n... (truncated)"

        return text if text else "No readable content found"

    except Exception:
        # Fallback to raw text if parsing fails
        return html[:max_length]


class WebFetchParams(BaseModel):
    """Parameters for WebFetchTool."""

    url: str


class WebSearchParams(BaseModel):
    """Parameters for WebSearchTool."""

    query: str


class WebFetchTool(Tool):
    """Fetch web page content with network restrictions."""

    parameters_model = WebFetchParams

    def __init__(self, safety_config: SafetyConfig | None = None):
        super().__init__(
            name="web_fetch",
            description="Fetch content from a URL and extract readable text.",
        )

        if safety_config:
            self.validator = SecurityValidator(safety_config)
        else:
            # Default to allowing network if no config provided
            self.validator = SecurityValidator(SafetyConfig(allow_network=True))

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
            if AsyncWebCrawler is not None:
                async with AsyncWebCrawler(verbose=True) as crawler:
                    res = await crawler.arun(url=url)
                    if hasattr(res, "success") and res.success:  # type: ignore
                        content = res.markdown if hasattr(res, "markdown") else ""  # type: ignore
                        if isinstance(content, str) and len(content) > 15000:
                            content = content[:15000] + "\n... (truncated)"
                        return ToolResult(content=str(content))

                    error_msg = getattr(res, "error_message", "Unknown error")  # type: ignore
                    return ToolResult(error=f"Failed to fetch {url}: {error_msg}")

            import httpx

            response = await httpx.AsyncClient(follow_redirects=True, timeout=20).get(url)
            response.raise_for_status()
            content = html_to_markdown(response.text, max_length=15000)
            return ToolResult(content=content)
        except Exception as e:
            return ToolResult(error=str(e))


class WebSearchTool(Tool):
    """Search the web with network restrictions."""

    parameters_model = WebSearchParams

    def __init__(self, safety_config: SafetyConfig | None = None):
        super().__init__(
            name="web_search",
            description="Search the web for information.",
        )

        if safety_config:
            self.validator = SecurityValidator(safety_config)
        else:
            self.validator = SecurityValidator(SafetyConfig(allow_network=False))

    async def _fetch_search_result(self, crawler: AsyncWebCrawler, url: str, title: str, snippet: str) -> str:
        content = ""
        try:
            res = await crawler.arun(url=url)
            if hasattr(res, "success") and res.success: # type: ignore
                content = getattr(res, "markdown", "") # type: ignore
                if isinstance(content, str) and len(content) > 4000:
                    content = content[:4000] + "\n... (truncated)"
        except Exception:
            # Use snippet from search result if fetch fails
            content = snippet[:500] if snippet else ""

        if not content:
            content = "[Content could not be fetched]"

        return f"- {title}: {url}\n  {content}"

    async def execute(self, query: str, **kwargs) -> ToolResult:
        """Search the web with safety checks."""
        if not self.validator.config.allow_network:
            return ToolResult(error="Web search is disabled")

        if self.validator.requires_approval("web_search"):
            approved = self.validator.get_approval("web_search", f"search: {query}")
            if not approved:
                return ToolResult(error="Web search requires approval")

        try:
            import io
            import sys
            from ddgs import DDGS

            old_stdout = sys.stdout
            old_stderr = sys.stderr
            try:
                sys.stdout = io.StringIO()
                sys.stderr = io.StringIO()
                ddgs = DDGS()
                results = list(ddgs.text(query, max_results=5))
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

            if not results:
                return ToolResult(content="No results found.")

            formatted = []
            if AsyncWebCrawler is None:
                for r in results:
                    title = r.get("title", "")
                    url = r.get("href", "")
                    snippet = r.get("body", "")
                    formatted.append(f"- {title}: {url}\n  {snippet[:500]}")
                return ToolResult(content="\n\n".join(formatted))

            async with AsyncWebCrawler(verbose=False) as crawler:
                tasks = []
                for r in results:
                    tasks.append(
                        self._fetch_search_result(
                            crawler,
                            r.get("href", ""),
                            r.get("title", ""),
                            r.get("body", "")
                        )
                    )

                gathered_results = await asyncio.gather(*tasks, return_exceptions=True)

                for i, r in enumerate(gathered_results):
                    if isinstance(r, Exception):
                        snippet = results[i].get("body", "")
                        title = results[i].get("title", "")
                        url = results[i].get("href", "")
                        formatted.append(f"- {title}: {url}\n  {snippet[:500]}")
                    else:
                        formatted.append(r)

            return ToolResult(content="\n\n".join(formatted))
        except Exception as e:
            return ToolResult(error=f"Search failed: {e}")
