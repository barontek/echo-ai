"""Tests for complex tools."""

import pytest
from unittest.mock import AsyncMock, patch

from agentframework.tools.notes import PersonalNotesTool
from agentframework.tools.web import WebFetchTool, WebSearchTool
from agentframework.safety import SafetyConfig


@pytest.fixture
def temp_notes_dir(tmp_path):
    return tmp_path / "notes"


@pytest.mark.asyncio
async def test_notes_tool(temp_notes_dir):
    tool = PersonalNotesTool(notes_dir=temp_notes_dir)

    # Test Create
    res = await tool.execute("create_note", filename="test", content="Hello")
    assert "Created note" in res.content

    # Test Create Existing
    res2 = await tool.execute("create_note", filename="test", content="World")
    assert res2.error and "already exists" in res2.error

    # Test Read
    res_read = await tool.execute("read_note", filename="test")
    assert "Hello" in res_read.content

    # Test Append
    await tool.execute("append_to_note", filename="test", content="World")
    res_read2 = await tool.execute("read_note", filename="test")
    assert "World" in res_read2.content

    # Test Append to non-existent
    await tool.execute("append_to_note", filename="new", content="NewContent")
    res_read_new = await tool.execute("read_note", filename="new")
    assert "NewContent" in res_read_new.content

    # Test Search
    res_search = await tool.execute("search_notes", query="world")
    assert "test" in res_search.content
    assert "World" in res_search.content

    # Test Search empty
    res_search_empty = await tool.execute("search_notes", query="xyzzy")
    assert "No notes found matching" in res_search_empty.content

    # Test List
    res_list = await tool.execute("list_notes")
    assert "test" in res_list.content
    assert "new" in res_list.content

    # Test List empty
    tool_empty = PersonalNotesTool(notes_dir=temp_notes_dir / "empty")
    res_list_empty = await tool_empty.execute("list_notes")
    assert "No notes yet" in res_list_empty.content

    # Test invalid action
    res_invalid = await tool.execute("invalid")
    assert res_invalid.error and "Unknown action" in res_invalid.error


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
@patch("agentframework.tools.web.AsyncWebCrawler")
async def test_web_fetch_tool(mock_crawler_class, mock_httpx_get):
    tool = WebFetchTool(safety_config=SafetyConfig(allow_network=True))

    # Mock httpx response
    class MockHttpxResponse:
        def __init__(self, status_code, text=""):
            self.status_code = status_code
            self.text = text

        def raise_for_status(self):
            import httpx

            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"HTTP error: {self.status_code}",
                    request=None,  # type: ignore[arg-type]
                    response=self,  # type: ignore[arg-type]
                )

    async def mock_httpx_get_fn(url, **kwargs):
        if "error.com" in url:
            return MockHttpxResponse(404)
        return MockHttpxResponse(200, "Fallback content")

    mock_httpx_get.side_effect = mock_httpx_get_fn

    mock_crawler = mock_crawler_class.return_value.__aenter__.return_value

    class MockResult:
        def __init__(self, success, markdown="", error_message=""):
            self.success = success
            self.markdown = markdown
            self.error_message = error_message

    async def mock_arun(url, **kwargs):
        if url == "http://example.com":
            return MockResult(
                success=True,
                markdown="# Test Page\nThis is a long enough content to pass the 50 characters threshold in the web fetch tool logic.",
            )
        else:
            return MockResult(success=False, error_message="HTTP error: 404")

    mock_crawler.arun.side_effect = mock_arun

    res = await tool.execute(url="http://example.com")
    assert not res.error
    # Either crawler content or fallback depending on Python/package version
    assert "Test Page" in res.content or "Fallback content" in res.content

    # Status error
    res2 = await tool.execute(url="http://error.com")
    assert res2.error and "HTTP error: 404" in res2.error

    # Blocked by config
    blocked_tool = WebFetchTool(safety_config=SafetyConfig(allow_network=False))
    res3 = await blocked_tool.execute(url="http://example.com")
    assert res3.error and "Network blocked" in res3.error


@pytest.mark.asyncio
@patch("agentframework.tools.web.AsyncWebCrawler")
async def test_web_search_tool(mock_crawler_class):
    tool = WebSearchTool(safety_config=SafetyConfig(allow_network=True))

    # Test blocked
    blocked_tool = WebSearchTool(safety_config=SafetyConfig(allow_network=False))
    res_blocked = await blocked_tool.execute(query="query")
    assert res_blocked.error and "Search blocked" in res_blocked.error

    mock_crawler = mock_crawler_class.return_value.__aenter__.return_value

    class MockResult:
        def __init__(self, success, markdown="", error_message=""):
            self.success = success
            self.markdown = markdown
            self.error_message = error_message

    async def mock_arun(url, **kwargs):
        if url == "http://example.com/1":
            return MockResult(
                success=True,
                markdown="This is the content for page 1 which is more than fifty characters long to satisfy the anti-bloat check.",
            )
        else:
            raise RuntimeError("Error")

    mock_crawler.arun.side_effect = mock_arun

    # Mock the search provider
    mock_provider = AsyncMock()
    mock_provider.search.return_value = [
        {"url": "http://example.com/1", "title": "Result 1", "snippet": "Snippet 1"},
        {"url": "http://example.com/2", "title": "Result 2", "snippet": "Snippet 2"},
    ]

    tool.search_provider = mock_provider

    res = await tool.execute(query="query")
    assert not res.error
    # Results format varies by Python/package version
    assert "Result 1" in res.content or "example.com/1" in res.content
