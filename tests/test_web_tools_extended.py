import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from src.agentframework.tools.web import html_to_markdown, WebFetchTool, WebSearchTool
from src.agentframework.safety import SafetyConfig


def test_html_to_markdown_fallback():
    # Simulate BeautifulSoup error by passing something that causes an exception
    # e.g. None or something not a string
    with patch(
        "src.agentframework.tools.web.BeautifulSoup", side_effect=Exception("BS error")
    ):
        res = html_to_markdown("<html>some html</html>", max_length=10)
        assert res == "<html>some"  # Fallback to raw text truncated


def test_html_to_markdown_complex():
    html = """
    <html>
        <header>Header</header>
        <nav>Nav</nav>
        <main>
            <article>
                <h1>Title</h1>
                <p>Paragraph 1</p>
                <script>alert(1)</script>
                <style>body {color: red}</style>
                <p>Paragraph 2</p>
            </article>
        </main>
        <footer>Footer</footer>
    </html>
    """
    res = html_to_markdown(html)
    assert "Title" in res
    assert "Paragraph 1" in res
    assert "Paragraph 2" in res
    assert "Header" not in res
    assert "Nav" not in res
    assert "Footer" not in res
    assert "alert(1)" not in res


@pytest.mark.asyncio
async def test_web_fetch_tool_safety():
    # Test network blocked
    config = SafetyConfig(allow_network=False)
    tool = WebFetchTool(safety_config=config)
    res = await tool.execute(url="http://example.com")
    assert res.error is not None
    assert "Network blocked" in res.error


@pytest.mark.asyncio
async def test_web_fetch_tool_approval():
    # Test requires approval
    config = SafetyConfig(allow_network=True, require_approval_for=["web_fetch"])
    tool = WebFetchTool(safety_config=config)

    with patch.object(tool.validator, "get_approval", return_value=False):
        res = await tool.execute(url="http://example.com")
        assert res.error == "Web fetch requires approval"


@pytest.mark.asyncio
async def test_web_fetch_tool_httpx_fallback():
    tool = WebFetchTool()

    # Mock AsyncWebCrawler to be None to force httpx Path
    with (
        patch("src.agentframework.tools.web.AsyncWebCrawler", None),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>Found it</body></html>"
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        res = await tool.execute(url="http://example.com")
        assert res.content == "Found it"


@pytest.mark.asyncio
async def test_web_search_tool_disabled():
    config = SafetyConfig(allow_network=False)
    tool = WebSearchTool(safety_config=config)
    res = await tool.execute(query="test")
    assert res.error == "Web search is disabled"


@pytest.mark.asyncio
async def test_web_search_tool_no_results():
    tool = WebSearchTool(safety_config=SafetyConfig(allow_network=True))

    # Mock DDGS at its source since it's a local import in web.py
    with patch("ddgs.DDGS") as mock_ddgs_cls:
        mock_ddgs = MagicMock()
        mock_ddgs.text.return_value = []
        mock_ddgs_cls.return_value = mock_ddgs

        res = await tool.execute(query="no results")
        assert res.content == "No results found."


@pytest.mark.asyncio
async def test_web_search_tool_failure():
    tool = WebSearchTool(safety_config=SafetyConfig(allow_network=True))

    # Mock DDGS at its source
    with patch("ddgs.DDGS", side_effect=Exception("DDGS error")):
        res = await tool.execute(query="fail")
        assert res.error is not None and "Search failed" in res.error
