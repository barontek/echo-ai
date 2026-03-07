"""Tests for complex tools."""

import pytest
from unittest.mock import patch
import httpx
import respx

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
    assert "already exists" in res2.error

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
    assert "world" in res_search.content

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
    assert "Unknown action" in res_invalid.error


@pytest.mark.asyncio
@respx.mock
async def test_web_fetch_tool():
    tool = WebFetchTool(safety_config=SafetyConfig(allow_network=True))

    respx.get("http://example.com").mock(
        return_value=httpx.Response(
            200,
            text="<html><body><h1>Test Page</h1><p>Content goes here</p><script>alert('hide')</script></body></html>"
        )
    )

    res = await tool.execute(url="http://example.com")
    assert not res.error
    assert "Test Page" in res.content
    assert "Content goes here" in res.content
    assert "alert" not in res.content

    # Status error
    respx.get("http://error.com").mock(
        return_value=httpx.Response(404)
    )
    res2 = await tool.execute(url="http://error.com")
    assert "HTTP error: 404" in res2.error

    # Blocked by config
    blocked_tool = WebFetchTool(safety_config=SafetyConfig(allow_network=False))
    res3 = await blocked_tool.execute(url="http://example.com")
    assert "Network blocked" in res3.error


@pytest.mark.asyncio
@respx.mock
async def test_web_search_tool():
    tool = WebSearchTool(safety_config=SafetyConfig(allow_network=True))

    # Test blocked
    blocked_tool = WebSearchTool(safety_config=SafetyConfig(allow_network=False))
    res_blocked = await blocked_tool.execute(query="query")
    assert "Web search is disabled" in res_blocked.error

    # Test mock DDGS
    with patch("ddgs.DDGS") as mock_ddgs:
        instance = mock_ddgs.return_value
        instance.text.return_value = [
            {"href": "http://example.com/1", "title": "Result 1", "body": "Snippet 1"},
            {"href": "http://example.com/2", "title": "Result 2", "body": "Snippet 2"},
        ]

        respx.get("http://example.com/1").mock(return_value=httpx.Response(200, text="<html><body>Page 1 Content</body></html>"))
        respx.get("http://example.com/2").mock(side_effect=httpx.ConnectError("Error")) # Will fallback to snippet

        res = await tool.execute(query="query")
        assert not res.error
        assert "Page 1 Content" in res.content
        assert "Result 2: http://example.com/2" in res.content
        assert "Snippet 2" in res.content
