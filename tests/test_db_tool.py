import pytest
import sqlite3
from pathlib import Path
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
def session_db(tmp_path):
    db_path = tmp_path / "agent_sessions.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, data TEXT)")
    cursor.execute("INSERT INTO sessions (id, data) VALUES ('s1', 'encrypted-data')")
    conn.commit()
    conn.close()
    return str(db_path)


@pytest.fixture
def query_tool():
    return SQLiteQueryTool(safety_config=SafetyConfig(require_approval_for=[]))


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
    assert "read-only SELECT/WITH queries are permitted" in res.error


@pytest.mark.asyncio
async def test_sqlite_query_missing_db(query_tool):
    res = await query_tool.execute(db_path="missing.db", query="SELECT * FROM users")
    assert res.error
    assert "Database file not found" in res.error


@pytest.mark.asyncio
async def test_sqlite_query_rejects_session_db(session_db, tmp_path):
    """Verify querying the session database itself is rejected, even with approval disabled."""
    # Tool with session_db_path set to the session database
    tool = SQLiteQueryTool(
        safety_config=SafetyConfig(require_approval_for=[]),
        session_db_path=session_db,
    )
    res = await tool.execute(db_path=session_db, query="SELECT * FROM sessions")
    assert res.error
    assert "Access to the session database via this tool is not permitted." in res.error


@pytest.mark.asyncio
async def test_sqlite_query_allows_other_db(session_db, test_db):
    """Verify non-session databases still work when session_db_path is set."""
    tool = SQLiteQueryTool(
        safety_config=SafetyConfig(require_approval_for=[]),
        session_db_path=session_db,
    )
    res = await tool.execute(db_path=test_db, query="SELECT * FROM users")
    assert not res.error
    assert "Alice" in res.content


@pytest.mark.asyncio
async def test_sqlite_schema_rejects_session_db(session_db, tmp_path):
    """Verify extracting schema from the session database is rejected."""
    tool = SQLiteSchemaTool(
        safety_config=SafetyConfig(),
        session_db_path=session_db,
    )
    res = await tool.execute(db_path=session_db)
    assert res.error
    assert "Access to the session database via this tool is not permitted." in res.error


@pytest.mark.asyncio
async def test_sqlite_schema_allows_other_db(session_db, test_db):
    """Verify non-session databases still work when session_db_path is set."""
    tool = SQLiteSchemaTool(
        safety_config=SafetyConfig(),
        session_db_path=session_db,
    )
    res = await tool.execute(db_path=test_db)
    assert not res.error
    assert "Table: users" in res.content


@pytest.mark.asyncio
async def test_sqlite_schema_resolves_realpath(session_db, tmp_path):
    """Verify the guard works even when the query path differs via symlinks."""
    link = tmp_path / "link.db"
    link.symlink_to(Path(session_db))
    tool = SQLiteSchemaTool(
        safety_config=SafetyConfig(),
        session_db_path=session_db,
    )
    res = await tool.execute(db_path=str(link))
    assert res.error
    assert "Access to the session database via this tool is not permitted." in res.error


@pytest.mark.asyncio
async def test_sqlite_query_resolves_realpath(session_db, tmp_path):
    """Verify the guard works even when the query path differs via symlinks."""
    link = tmp_path / "link.db"
    link.symlink_to(Path(session_db))
    tool = SQLiteQueryTool(
        safety_config=SafetyConfig(require_approval_for=[]),
        session_db_path=session_db,
    )
    res = await tool.execute(db_path=str(link), query="SELECT * FROM sessions")
    assert res.error
    assert "Access to the session database via this tool is not permitted." in res.error


@pytest.mark.asyncio
async def test_sqlite_query_rejects_case_variation(session_db, tmp_path):
    """Verify the guard works on case-insensitive filesystems via different-case path."""
    parent = Path(session_db).parent
    name = Path(session_db).name
    # Check if filesystem is case-sensitive: write a lower-case temp file and try upper-case read
    probe = parent / ".case_probe_lower"
    probe.write_text("")
    is_case_sensitive = not (parent / ".CASE_PROBE_LOWER").exists()
    probe.unlink()
    if is_case_sensitive:
        pytest.skip("Filesystem is case-sensitive; case-variation bypass is not applicable.")

    upper_name = name.upper() if name != name.upper() else name.lower()
    upper_path = str(parent / upper_name)
    tool = SQLiteQueryTool(
        safety_config=SafetyConfig(require_approval_for=[]),
        session_db_path=session_db,
    )
    res = await tool.execute(db_path=upper_path, query="SELECT * FROM sessions")
    assert res.error
    assert "Access to the session database via this tool is not permitted." in res.error


@pytest.mark.asyncio
async def test_sqlite_schema_rejects_case_variation(session_db, tmp_path):
    parent = Path(session_db).parent
    base = Path(session_db).name
    probe = parent / ".case_probe_schema"
    probe.write_text("")
    is_case_sensitive = not (parent / ".CASE_PROBE_SCHEMA").exists()
    probe.unlink()
    if is_case_sensitive:
        pytest.skip("Filesystem is case-sensitive.")

    upper_name = base.upper() if base != base.upper() else base.lower()
    alt_path = str(parent / upper_name)
    tool = SQLiteSchemaTool(
        safety_config=SafetyConfig(),
        session_db_path=session_db,
    )
    res = await tool.execute(db_path=alt_path)
    assert res.error
    assert "Access to the session database via this tool is not permitted." in res.error
