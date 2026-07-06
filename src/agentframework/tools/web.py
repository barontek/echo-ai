"""Web tools for fetching and searching with network restrictions."""

import asyncio
import platform
from typing import Any
from bs4 import BeautifulSoup
from pydantic import BaseModel
import markdownify
import httpx

try:
    from crawl4ai import AsyncWebCrawler
except ImportError:  # pragma: no cover - optional runtime dependency
    AsyncWebCrawler = None

import logging
from ..safety import SafetyConfig, SecurityValidator
from . import Tool, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_LIMITS = {
    "max_web_fetch_chars": 15000,
    "max_search_result_snippet": 500,
    "min_fetch_content_chars": 50,
    "search_result_truncate": 1000,
}

_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Get or create a shared HTTP client with connection pooling."""
    global _http_client
    if _http_client is None:
        os_name = platform.system()
        ua = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        if os_name == "Darwin":
            ua = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            )
        elif os_name == "Windows":
            ua = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            )
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=True,
            max_redirects=5,
            limits=httpx.Limits(
                max_keepalive_connections=10, max_connections=20
            ),
            headers={"User-Agent": ua},
        )
    return _http_client


async def close_http_client() -> None:
    """Close the shared HTTP client."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


def validate_url(url: str) -> tuple[bool, str]:
    """Validate URL for security and format.

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not url:
        return False, "URL cannot be empty"

    url = url.strip()

    if len(url) > 2048:
        return False, "URL exceeds maximum length of 2048 characters"

    allowed_schemes = ("http", "https")
    if not url.lower().startswith(allowed_schemes):
        return False, f"URL must start with {allowed_schemes}"

    dangerous_patterns = ["javascript:", "data:", "vbscript:", "file:"]
    if any(url.lower().startswith(p) for p in dangerous_patterns):
        return False, "Dangerous URL scheme not allowed"

    return True, ""


def html_to_markdown(html: str, max_length: int = 10000) -> str:
    """Parse HTML and extract readable markdown using markdownify."""
    try:
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(
            [
                "script",
                "style",
                "nav",
                "header",
                "footer",
                "aside",
                "iframe",
                "noscript",
            ]
        ):
            tag.decompose()

        main = soup.find("main") or soup.find("article") or soup.find("body") or soup

        md = markdownify.markdownify(
            str(main),
            heading_style="ATX",
            strip=["script", "style"],
        )

        text = md or ""

        if len(text) > max_length:
            text = text[:max_length] + "\n... (truncated)"

        return text if text else "No readable content found"

    except (TypeError, ValueError, AttributeError):
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

    def __init__(
        self, safety_config: SafetyConfig | None = None, limits: dict | None = None
    ):
        super().__init__(
            name="web_fetch",
            description="Fetch content from a URL and extract readable text.",
        )

        self.limits = {**DEFAULT_LIMITS, **(limits or {})}

        if safety_config:
            self.validator = SecurityValidator(safety_config)
        else:
            # Default to allowing network if no config provided
            self.validator = SecurityValidator(SafetyConfig(allow_network=True))

    async def execute(self, url: str, **kwargs) -> ToolResult:
        """Fetch the URL with safety checks."""
        is_valid, error_msg = validate_url(url)
        if not is_valid:
            return ToolResult(error=f"Invalid URL: {error_msg}")

        allowed, reason = self.validator.check_network_allowed(url)
        if not allowed:
            return ToolResult(error=f"Network blocked: {reason}")

        if self.validator.requires_approval("web_fetch"):
            approved = await self.validator.get_approval_async("web_fetch", f"fetch: {url}")
            if not approved:
                return ToolResult(error="Web fetch requires approval")

        try:
            if AsyncWebCrawler is not None:
                try:
                    import re
                    from crawl4ai import CrawlerRunConfig
                    from crawl4ai.markdown_generation_strategy import (
                        DefaultMarkdownGenerator,
                    )
                    from crawl4ai.content_filter_strategy import PruningContentFilter

                    run_config = CrawlerRunConfig(
                        markdown_generator=DefaultMarkdownGenerator(
                            options={
                                "ignore_links": True,
                                "ignore_images": True,
                                "escape_html": True,
                            },
                            content_filter=PruningContentFilter(),
                        )
                    )

                    async with AsyncWebCrawler(verbose=True) as crawler:
                        res = await crawler.arun(url=url, magic=True, config=run_config)
                        if getattr(res, "success", False):  # type: ignore
                            content_obj = getattr(res, "markdown", "")  # type: ignore

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
                                content = re.sub(
                                    r"https?://(?:[a-zA-Z0-9]|[$-@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+",
                                    "",
                                    content,
                                )
                                content = re.sub(r"\n\s*\n", "\n", content)
                                content = content.strip()

                            min_chars = self.limits.get("min_fetch_content_chars", 50)
                            max_chars = self.limits.get("max_web_fetch_chars", 15000)
                            if content and len(str(content).strip()) > min_chars:
                                if (
                                    isinstance(content, str)
                                    and len(content) > max_chars
                                ):
                                    content = content[:max_chars] + "\n... (truncated)"
                                return ToolResult(content=str(content))
                except Exception as e:
                    logger.warning("Crawl4AI fetch failed, falling back to httpx: %s", e)

            max_chars = self.limits.get("max_web_fetch_chars", 15000)
            client = get_http_client()
            response = await client.get(url)
            response.raise_for_status()
            # Validate final URL after redirects to prevent SSRF
            if str(response.url) != url:
                allowed, reason = self.validator.check_network_allowed(str(response.url))
                if not allowed:
                    return ToolResult(error=f"Redirect target blocked: {reason}")
            content = html_to_markdown(response.text, max_length=max_chars)
            return ToolResult(content=content)
        except Exception as e:
            return ToolResult(error=str(e))


class WebSearchTool(Tool):
    """Search the web with network restrictions."""

    parameters_model = WebSearchParams

    def __init__(
        self,
        safety_config: SafetyConfig | None = None,
        limits: dict | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            name="web_search",
            description="Search the web for information.",
        )

        self.limits = {**DEFAULT_LIMITS, **(limits or {})}

        # Handle provider from kwargs (passed by config system)
        if "provider" in kwargs:
            self.limits["provider"] = kwargs["provider"]

        if safety_config:
            self.validator = SecurityValidator(safety_config)
        else:
            self.validator = SecurityValidator(SafetyConfig(allow_network=False))

        # Initialize search provider
        provider_type = self.limits.get("provider", "brave")
        from .search_providers import get_search_provider

        try:
            self.search_provider = get_search_provider(provider_type)
        except Exception as e:
            logger.warning(
                f"Failed to initialize search provider '{provider_type}': {e}"
            )
            self.search_provider = None

    async def _fetch_search_result(
        self, crawler: Any, index: int, url: str, title: str, snippet: str
    ) -> str:
        content = ""
        try:
            import uuid
            import re
            from crawl4ai import CrawlerRunConfig
            from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
            from crawl4ai.content_filter_strategy import PruningContentFilter

            run_config = CrawlerRunConfig(
                markdown_generator=DefaultMarkdownGenerator(
                    options={
                        "ignore_links": True,
                        "ignore_images": True,
                        "escape_html": True,
                    },
                    content_filter=PruningContentFilter(),
                )
            )

            res = await crawler.arun(
                url=url, session_id=str(uuid.uuid4()), magic=True, config=run_config
            )
            if getattr(res, "success", False):  # type: ignore
                content_obj = getattr(res, "markdown", "")  # type: ignore

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
                    content = re.sub(
                        r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+",
                        "",
                        content,
                    )
                    content = re.sub(r"\n\s*\n", "\n", content)
                    content = content.strip()

                truncate_limit = self.limits.get("search_result_truncate", 1000)
                if isinstance(content, str) and len(content) > truncate_limit:
                    content = content[:truncate_limit] + "\n... (truncated)"
        except Exception as e:
            logger.debug(f"Crawl4AI search result fetch failed: {e}")

        min_chars = self.limits.get("min_fetch_content_chars", 50)
        snippet_limit = self.limits.get("max_search_result_snippet", 500)
        if not content or len(str(content).strip()) < min_chars:
            content = (
                snippet[:snippet_limit] if snippet else "[Content could not be fetched]"
            )

        return f"{index}. {title}: {url}\n  {content}"

    async def execute(self, query: str, **kwargs) -> ToolResult:
        """Search the web with safety checks."""
        allowed, reason = self.validator.check_network_allowed("https://web-search")
        if not allowed:
            return ToolResult(error=f"Search blocked: {reason}")

        if self.validator.requires_approval("web_search"):
            approved = await self.validator.get_approval_async("web_search", f"search: {query}")
            if not approved:
                return ToolResult(error="Web search requires approval")

        if not self.search_provider:
            return ToolResult(error="Search provider not initialized")

        try:
            max_results = self.limits.get("max_search_results", 5)

            results = await asyncio.wait_for(
                self.search_provider.search(query, max_results=max_results),
                timeout=30.0,
            )

            if not results:
                return ToolResult(content="No results found.")

            formatted = []
            if AsyncWebCrawler is None:
                for idx, r in enumerate(results, 1):
                    title = r.get("title", "")
                    url = r.get("url", "")
                    snippet = r.get("snippet", "")
                    snippet_limit = self.limits.get("max_search_result_snippet", 500)
                    formatted.append(f"{idx}. {title}: {url}\n  {snippet[:snippet_limit]}")
                return ToolResult(content="\n\n".join(formatted))

            try:
                async with AsyncWebCrawler(verbose=False) as crawler:
                    coros = [
                        self._fetch_search_result(
                            crawler,
                            idx,
                            r.get("url", ""),
                            r.get("title", ""),
                            r.get("snippet", ""),
                        )
                        for idx, r in enumerate(results, 1)
                    ]

                    task_objects = [asyncio.ensure_future(c) for c in coros]
                    try:
                        gathered_results = await asyncio.wait_for(
                            asyncio.gather(*task_objects, return_exceptions=True),
                            timeout=60.0,
                        )
                    except asyncio.TimeoutError:
                        for t in task_objects:
                            if not t.done():
                                t.cancel()
                        raise

                    for i, r in enumerate(gathered_results):
                        if isinstance(r, Exception):
                            title = results[i].get("title", "")
                            snippet = results[i].get("snippet", "")
                            url = results[i].get("url", "")
                            snippet_limit = self.limits.get("max_search_result_snippet", 500)
                            formatted.append(f"{i+1}. {title}: {url}\n  {snippet[:snippet_limit]}")
                        else:
                            formatted.append(r)

                return ToolResult(content="\n\n".join(formatted))
            except Exception:
                logger.warning("Crawl4AI search crawl failed, returning snippet-only results")
                for idx, r in enumerate(results, 1):
                    title = r.get("title", "")
                    url = r.get("url", "")
                    snippet = r.get("snippet", "")
                    snippet_limit = self.limits.get("max_search_result_snippet", 500)
                    formatted.append(f"{idx}. {title}: {url}\n  {snippet[:snippet_limit]}")
                return ToolResult(content="\n\n".join(formatted))
        except asyncio.TimeoutError:
            return ToolResult(error="Search timed out")
        except Exception as e:
            return ToolResult(error=f"Search failed: {e}")
