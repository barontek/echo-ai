"""Web tools for fetching and searching with network restrictions."""

import httpx

from bs4 import BeautifulSoup
from pydantic import BaseModel

from ..safety import SafetyConfig, SecurityValidator
from . import Tool, ToolResult


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

    def _extract_readable_text(self, html: str, max_length: int = 10000) -> str:
        """Parse HTML and extract readable text using BeautifulSoup."""
        try:
            soup = BeautifulSoup(html, "html.parser")

            # Remove script, style, nav, header, footer elements
            for tag in soup(
                ["script", "style", "nav", "header", "footer", "aside", "iframe"]
            ):
                tag.decompose()

            # Get text from body or entire document
            body = soup.find("body")
            if body:
                text = body.get_text(separator="\n", strip=True)
            else:
                text = soup.get_text(separator="\n", strip=True)

            # Clean up whitespace
            lines = [line.strip() for line in text.split("\n")]
            lines = [line for line in lines if line]
            text = "\n".join(lines)

            # Truncate to max length
            if len(text) > max_length:
                text = text[:max_length] + "\n... (truncated)"

            return text if text else "No readable content found"

        except Exception:
            # Fallback to raw text if parsing fails
            return html[:10000]

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
                verify=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AgentBot/1.0)"},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

                # Extract readable text from HTML
                content = self._extract_readable_text(response.text)
                return ToolResult(content=content)
        except httpx.TimeoutException:
            return ToolResult(error="Request timed out")
        except httpx.HTTPStatusError as e:
            return ToolResult(error=f"HTTP error: {e.response.status_code}")
        except httpx.RequestError as e:
            return ToolResult(error=f"Request failed: {e}")
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
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                for r in results:
                    url = r.get("href", "")
                    title = r.get("title", "")

                    # Fetch full page content
                    content = ""
                    try:
                        resp = await client.get(url)
                        if resp.status_code == 200:
                            soup = BeautifulSoup(resp.text, "html.parser")

                            # Remove script, style, nav, header, footer elements
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

                            # Get text from main content areas
                            main = (
                                soup.find("main")
                                or soup.find("article")
                                or soup.find("body")
                            )
                            if main:
                                text = main.get_text(separator=" ", strip=True)
                            else:
                                text = soup.get_text(separator=" ", strip=True)

                            # Clean up whitespace
                            content = " ".join(text.split())[:2000]
                    except (httpx.RequestError, Exception):
                        content = r.get("body", "")[:500]

                    formatted.append(f"- {title}: {url}\n  {content}")

            return ToolResult(content="\n\n".join(formatted))
        except Exception as e:
            return ToolResult(error=f"Search failed: {e}")
