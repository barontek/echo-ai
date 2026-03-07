"""Tests for memory tool."""

import pytest
import tempfile
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


class TestMemoryPersistence:
    """Tests for persistent memory (list_facts + load_memories)."""

    @pytest.fixture
    def temp_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "memory.db"

    @pytest.fixture
    def tool(self, temp_db):
        return MemoryTool(db_path=temp_db)

    @pytest.mark.asyncio
    async def test_list_facts_empty(self, tool):
        result = await tool.execute(action="list_facts", query="")
        assert result.error is None
        assert "No memories" in result.content

    @pytest.mark.asyncio
    async def test_list_facts_all(self, tool):
        await tool.execute(action="save_fact", query="I like coffee", category="preference")
        await tool.execute(action="save_fact", query="My name is Alice", category="personal")
        result = await tool.execute(action="list_facts", query="")
        assert result.error is None
        assert "I like coffee" in result.content
        assert "My name is Alice" in result.content

    @pytest.mark.asyncio
    async def test_list_facts_category_filter(self, tool):
        await tool.execute(action="save_fact", query="I like coffee", category="preference")
        await tool.execute(action="save_fact", query="My name is Alice", category="personal")
        result = await tool.execute(action="list_facts", category="preference", query="")
        assert result.error is None
        assert "I like coffee" in result.content
        assert "My name is Alice" not in result.content

    def test_load_memories_empty(self, tool):
        result = tool.load_memories()
        assert result == ""

    @pytest.mark.asyncio
    async def test_load_memories_returns_all(self, tool):
        await tool.execute(action="save_fact", query="My name is Bob", category="personal")
        await tool.execute(action="save_fact", query="I prefer dark mode", category="preference")
        result = tool.load_memories()
        assert "My name is Bob" in result
        assert "I prefer dark mode" in result
        assert "[personal]" in result
        assert "[preference]" in result

    @pytest.mark.asyncio
    async def test_load_memories_category_filter(self, tool):
        await tool.execute(action="save_fact", query="My name is Bob", category="personal")
        await tool.execute(action="save_fact", query="I prefer dark mode", category="preference")
        result = tool.load_memories(categories=["personal"])
        assert "My name is Bob" in result
        assert "I prefer dark mode" not in result


class TestMemoryDeletion:
    """Tests for delete_fact and clear_facts actions."""

    @pytest.fixture
    def temp_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "memory.db"

    @pytest.fixture
    def tool(self, temp_db):
        from src.agentframework.safety import SafetyConfig
        safety = SafetyConfig(approval_callback=lambda tool, details: True)
        return MemoryTool(db_path=temp_db, safety_config=safety)

    @pytest.mark.asyncio
    async def test_delete_fact_exact_match(self, tool):
        await tool.execute(action="save_fact", query="My name is Carol")
        result = await tool.execute(action="delete_fact", query="My name is Carol")
        assert result.error is None
        assert "Deleted 1" in result.content
        # Confirm it's gone
        recall = await tool.execute(action="recall_fact", query="Carol")
        assert "Carol" not in recall.content

    @pytest.mark.asyncio
    async def test_delete_fact_partial_match(self, tool):
        await tool.execute(action="save_fact", query="I enjoy hiking on weekends")
        result = await tool.execute(action="delete_fact", query="hiking")
        assert result.error is None
        assert "Deleted 1" in result.content

    @pytest.mark.asyncio
    async def test_delete_fact_no_match(self, tool):
        result = await tool.execute(action="delete_fact", query="nonexistent fact xyz")
        assert result.error is None
        assert "No memory found" in result.content

    @pytest.mark.asyncio
    async def test_delete_fact_empty_query(self, tool):
        result = await tool.execute(action="delete_fact", query="")
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_clear_facts_all(self, tool):
        await tool.execute(action="save_fact", query="fact A", category="fact")
        await tool.execute(action="save_fact", query="fact B", category="personal")
        result = await tool.execute(action="clear_facts", query="")
        assert result.error is None
        assert "Cleared" in result.content
        # Confirm empty
        list_result = await tool.execute(action="list_facts", query="")
        assert "No memories" in list_result.content

    @pytest.mark.asyncio
    async def test_clear_facts_by_category(self, tool):
        await tool.execute(action="save_fact", query="pref A", category="preference")
        await tool.execute(action="save_fact", query="personal A", category="personal")
        result = await tool.execute(action="clear_facts", category="preference", query="")
        assert result.error is None
        assert "preference" in result.content
        # personal memory should still exist
        list_result = await tool.execute(action="list_facts", query="")
        assert "personal A" in list_result.content
        assert "pref A" not in list_result.content

    @pytest.mark.asyncio
    async def test_clear_facts_empty(self, tool):
        result = await tool.execute(action="clear_facts", query="")
        assert result.error is None
        assert "No memories to clear" in result.content

    @pytest.mark.asyncio
    async def test_delete_denied_when_user_rejects(self, temp_db):
        from src.agentframework.safety import SafetyConfig
        safety = SafetyConfig(approval_callback=lambda tool, details: False)
        tool = MemoryTool(db_path=temp_db, safety_config=safety)
        await tool.execute(action="save_fact", query="secret info")
        result = await tool.execute(action="delete_fact", query="secret info")
        assert result.error is not None
        assert "approval" in result.error.lower()
        # Memory should still exist
        recall = await tool.execute(action="recall_fact", query="secret")
        assert "secret info" in recall.content
