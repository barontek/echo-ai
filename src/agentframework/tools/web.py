"""Web tools for fetching and searching with network restrictions."""

import asyncio
from typing import Any
from bs4 import BeautifulSoup
from pydantic import BaseModel
import markdownify
try:
    from crawl4ai import AsyncWebCrawler
except ImportError:  # pragma: no cover - optional runtime dependency
    AsyncWebCrawler = None

import logging
from ..safety import SafetyConfig, SecurityValidator
from . import Tool, ToolResult

logger = logging.getLogger(__name__)


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
                try:
                    import re
                    from crawl4ai import CrawlerRunConfig
                    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
                    from crawl4ai.content_filter_strategy import PruningContentFilter

                    run_config = CrawlerRunConfig(
                        markdown_generator=DefaultMarkdownGenerator(
                            options={"ignore_links": True, "ignore_images": True, "escape_html": True},
                            content_filter=PruningContentFilter()
                        )
                    )

                    async with AsyncWebCrawler(verbose=True) as crawler:
                        res = await crawler.arun(url=url, magic=True, config=run_config)
                        if getattr(res, "success", False):  # type: ignore
                            content_obj = getattr(res, "markdown", "") # type: ignore

                            fit_md = getattr(content_obj, "fit_markdown", None)
                            raw_md = getattr(content_obj, "raw_markdown", None)

                            if fit_md:
                                content = fit_md
                            elif raw_md:
                                content = raw_md
                            elif isinstance(content_obj, str):
                                content = content_obj
                            else:
                                content = str(content_obj)

                            if content:
                                content = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', content)
                                content = re.sub(r'\n\s*\n', '\n', content)
                                content = content.strip()

                            if content and len(str(content).strip()) > 50:
                                if isinstance(content, str) and len(content) > 8000:
                                    content = content[:8000] + "\n... (truncated)"
                                return ToolResult(content=str(content))
                except Exception as e:
                    logger.debug(f"Crawl4AI fetch failed, falling back to httpx: {e}")

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

    async def _fetch_search_result(self, crawler: Any, url: str, title: str, snippet: str) -> str:
        content = ""
        try:
            import uuid
            import re
            from crawl4ai import CrawlerRunConfig
            from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
            from crawl4ai.content_filter_strategy import PruningContentFilter

            # Natively strip images and links to prevent token bloat
            run_config = CrawlerRunConfig(
                markdown_generator=DefaultMarkdownGenerator(
                    options={"ignore_links": True, "ignore_images": True, "escape_html": True},
                    content_filter=PruningContentFilter()
                )
            )

            res = await crawler.arun(url=url, session_id=str(uuid.uuid4()), magic=True, config=run_config)
            if getattr(res, "success", False): # type: ignore
                content_obj = getattr(res, "markdown", "") # type: ignore

                fit_md = getattr(content_obj, "fit_markdown", None)
                raw_md = getattr(content_obj, "raw_markdown", None)

                if fit_md:
                    content = fit_md
                elif raw_md:
                    content = raw_md
                elif isinstance(content_obj, str):
                    content = content_obj
                else:
                    content = str(content_obj)

                if content:
                    # Final regex sweep to catch lingering URLs and excessive whitespace
                    content = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', content)
                    content = re.sub(r'\n\s*\n', '\n', content)
                    content = content.strip()

                # DECREASED TRUNCATION: Limit to 1000 chars to force AI to focus on top data
                if isinstance(content, str) and len(content) > 1000:
                    content = content[:1000] + "\n... (truncated)"
        except Exception as e:
            logger.debug(f"Crawl4AI search result fetch failed: {e}")

        if not content or len(str(content).strip()) < 50:
            content = snippet[:500] if snippet else "[Content could not be fetched]"

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
