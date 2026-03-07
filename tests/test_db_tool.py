import pytest
import sqlite3
from src.agentframework.tools.db import SQLiteQueryTool, SQLiteSchemaTool
from src.agentframework.safety import SafetyConfig

@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
    cursor.execute("INSERT INTO users (name, age) VALUES ('Alice', 30), ('Bob', 25)")
    conn.commit()
    conn.close()
    return str(db_path)

@pytest.fixture
def query_tool():
    return SQLiteQueryTool(safety_config=SafetyConfig())

@pytest.fixture
def schema_tool():
    return SQLiteSchemaTool(safety_config=SafetyConfig())

@pytest.mark.asyncio
async def test_sqlite_schema(schema_tool, test_db):
    res = await schema_tool.execute(db_path=test_db)
    assert not res.error
    assert "Table: users" in res.content
    assert "id [INTEGER] (PRIMARY KEY)" in res.content
    assert "name [TEXT]" in res.content

@pytest.mark.asyncio
async def test_sqlite_query_select(query_tool, test_db):
    res = await query_tool.execute(db_path=test_db, query="SELECT * FROM users")
    assert not res.error
    assert "Alice" in res.content
    assert "Bob" in res.content
    assert "| id | name | age |" in res.content

@pytest.mark.asyncio
async def test_sqlite_query_destructive(query_tool, test_db):
    res = await query_tool.execute(db_path=test_db, query="DROP TABLE users")
    assert res.error
    assert "read-only SELECT queries are permitted" in res.error

@pytest.mark.asyncio
async def test_sqlite_query_missing_db(query_tool):
    res = await query_tool.execute(db_path="missing.db", query="SELECT * FROM users")
    assert res.error
    assert "Database file not found" in res.error
