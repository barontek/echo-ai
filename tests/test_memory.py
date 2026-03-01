"""Tests for memory tool."""

import pytest
import tempfile
import asyncio
from pathlib import Path

from src.agentframework.tools.memory import MemoryTool


class TestMemoryTool:
    """Tests for MemoryTool."""

    @pytest.fixture
    def temp_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "memory.db"

    @pytest.fixture
    def tool(self, temp_db):
        return MemoryTool(db_path=temp_db)

    def test_tool_initialization(self, temp_db):
        tool = MemoryTool(db_path=temp_db)
        assert tool.name == "memory"
        assert tool.db_path == temp_db

    def test_tool_schema(self, temp_db):
        tool = MemoryTool(db_path=temp_db)
        schema = tool.schema
        assert schema["function"]["name"] == "memory"
        assert "action" in schema["function"]["parameters"]["properties"]
        assert "query" in schema["function"]["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_save_fact(self, tool):
        result = await tool.execute(action="save_fact", query="my name is John")
        assert result.error is None
        assert "Remembered" in result.content

    @pytest.mark.asyncio
    async def test_save_fact_with_category(self, tool):
        result = await tool.execute(
            action="save_fact",
            query="I prefer dark mode",
            category="preference"
        )
        assert result.error is None

    @pytest.mark.asyncio
    async def test_recall_fact(self, tool):
        await tool.execute(action="save_fact", query="my name is John")
        result = await tool.execute(action="recall_fact", query="name")
        assert result.error is None
        assert "John" in result.content

    @pytest.mark.asyncio
    async def test_recall_no_matches(self, tool):
        await tool.execute(action="save_fact", query="my name is John")
        result = await tool.execute(action="recall_fact", query="完全不匹配的查询")
        assert result.error is None
        assert "don't have any memories" in result.content.lower()

    @pytest.mark.asyncio
    async def test_recall_multiple_terms(self, tool):
        await tool.execute(action="save_fact", query="my name is John")
        await tool.execute(action="save_fact", query="john lives in NYC")
        
        result = await tool.execute(action="recall_fact", query="john name")
        assert result.error is None

    @pytest.mark.asyncio
    async def test_unknown_action(self, tool):
        result = await tool.execute(action="unknown_action", query="test")
        assert result.error is not None
        assert "Unknown action" in result.error

    @pytest.mark.asyncio
    async def test_save_multiple_facts(self, tool):
        await tool.execute(action="save_fact", query="I like pizza")
        await tool.execute(action="save_fact", query="I hate broccoli")
        await tool.execute(action="save_fact", query="My favorite color is blue")
        
        result = await tool.execute(action="recall_fact", query="favorite")
        assert result.error is None
        assert "blue" in result.content

    @pytest.mark.asyncio
    async def test_category_filtering(self, tool):
        await tool.execute(action="save_fact", query="fact 1", category="fact")
        await tool.execute(action="save_fact", query="pref 1", category="preference")
        await tool.execute(action="save_fact", query="fact 2", category="fact")
        
        result = await tool.execute(action="recall_fact", query="fact")
        assert result.error is None
        assert "fact 1" in result.content or "fact 2" in result.content


class TestMemoryToolEdgeCases:
    """Edge case tests for MemoryTool."""

    @pytest.fixture
    def temp_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "memory.db"

    @pytest.fixture
    def tool(self, temp_db):
        return MemoryTool(db_path=temp_db)

    @pytest.mark.asyncio
    async def test_empty_query_save(self, tool):
        result = await tool.execute(action="save_fact", query="")
        assert result.error is None

    @pytest.mark.asyncio
    async def test_empty_query_recall(self, tool):
        await tool.execute(action="save_fact", query="some fact")
        result = await tool.execute(action="recall_fact", query="")
        assert result.error is None

    @pytest.mark.asyncio
    async def test_unicode_content(self, tool):
        result = await tool.execute(
            action="save_fact",
            query="我的名字是张三"
        )
        assert result.error is None
        
        result = await tool.execute(action="recall_fact", query="名字")
        assert result.error is None
        assert "张" in result.content

    @pytest.mark.asyncio
    async def test_special_characters(self, tool):
        result = await tool.execute(
            action="save_fact",
            query="Email: test@example.com | Phone: 555-1234"
        )
        assert result.error is None

    @pytest.mark.asyncio
    async def test_long_content(self, tool):
        long_text = "A" * 10000
        result = await tool.execute(action="save_fact", query=long_text)
        assert result.error is None

    @pytest.mark.asyncio
    async def test_many_recalls(self, tool):
        for i in range(10):
            await tool.execute(action="save_fact", query=f"fact number {i}")
        
        result = await tool.execute(action="recall_fact", query="fact")
        assert result.error is None
