"""Tool for querying local SQLite databases."""

import re
import sqlite3
import os
from pydantic import BaseModel, Field

from ..safety import SafetyConfig, SecurityValidator
from . import Tool, ToolResult


def _same_file(path_a: str, path_b: str) -> bool:
    try:
        return os.path.exists(path_a) and os.path.exists(path_b) and os.path.samefile(path_a, path_b)
    except OSError:
        return False


def _is_session_db(session_db_path: str | None, db_path: str) -> bool:
    if not session_db_path:
        return False
    resolved = os.path.realpath(db_path)
    if resolved == os.path.realpath(session_db_path):
        return True
    return _same_file(session_db_path, db_path)


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL line comments (--) and block comments (/* */)."""
    sql = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    return sql


class SQLiteQueryParams(BaseModel):
    """Parameters for SQLiteQueryTool."""

    db_path: str = Field(description="The path to the local SQLite database file (.db or .sqlite).")
    query: str = Field(description="The SELECT query to execute.")


class SQLiteSchemaParams(BaseModel):
    """Parameters for SQLiteSchemaTool."""

    db_path: str = Field(description="The path to the local SQLite database file (.db or .sqlite).")


class SQLiteQueryTool(Tool):
    """Execute read-only SQL queries against a local SQLite database."""

    parameters_model = SQLiteQueryParams

    def __init__(self, safety_config: SafetyConfig | None = None, session_db_path: str | None = None):
        super().__init__(
            name="sqlite_query",
            description="Execute read-only SQL queries (SELECT) against a local SQLite database. Ensure you use the schema tool first to understand the tables.",
        )
        if safety_config:
            self.validator = SecurityValidator(safety_config)
        else:
            self.validator = SecurityValidator(SafetyConfig(require_approval_for=["sqlite_query"]))
        self.session_db_path = os.path.realpath(session_db_path) if session_db_path else None

    async def execute(self, db_path: str, query: str, **kwargs) -> ToolResult:
        """Execute the SQLite query."""
        if _is_session_db(self.session_db_path, db_path):
            return ToolResult(error="Access to the session database via this tool is not permitted.")

        if self.validator.requires_approval("sqlite_query"):
            approved = await self.validator.get_approval_async(
                "sqlite_query", f"Querying {db_path}:\n{query}"
            )
            if not approved:
                return ToolResult(error="Database query requires approval")

        if not os.path.exists(db_path):
            return ToolResult(error=f"Database file not found: {db_path}")

        # Allowlist-based guardrail against destructive queries
        stripped = _strip_sql_comments(query).strip()
        if not stripped:
            return ToolResult(error="Empty query after stripping comments.")
        first_word = stripped.upper().split(None, 1)[0]
        allowed_prefixes = {"SELECT", "WITH", "EXPLAIN"}
        if first_word not in allowed_prefixes:
            return ToolResult(error="Only read-only SELECT/WITH queries are permitted.")

        conn = None
        try:
            # We run synchronously since sqlite3 is synchronous
            # For massive queries we'd use a threadpool, but this is a lightweight agent tool
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(query)
            rows = cursor.fetchmany(100) # Limit to 100 rows to prevent context blowing up

            if not rows:
                return ToolResult(content="Query executed successfully. No rows returned.")

            # Formatting table output
            columns = rows[0].keys()

            # Create markdown table
            header = "| " + " | ".join(columns) + " |"
            separator = "| " + " | ".join(["---"] * len(columns)) + " |"

            table_rows = []
            for row in rows:
                table_rows.append("| " + " | ".join(str(row[col]) for col in columns) + " |")

            output = f"Returned {len(rows)} rows (limited to 100 max):\n\n"
            output += "\n".join([header, separator] + table_rows)

            return ToolResult(content=output)

        except sqlite3.Error as e:
            return ToolResult(error=f"SQLite Error: {e}")
        except Exception as e:
            return ToolResult(error=str(e))
        finally:
            if conn:
                conn.close()


class SQLiteSchemaTool(Tool):
    """Extract schema information (tables and columns) from a local SQLite database."""

    parameters_model = SQLiteSchemaParams

    def __init__(self, safety_config: SafetyConfig | None = None, session_db_path: str | None = None):
        super().__init__(
            name="sqlite_schema",
            description="Extract the table schema and column definitions from a local SQLite database file.",
        )
        # Schema reads are generally safe so we don't strictly require approval by default
        self.validator = SecurityValidator(safety_config or SafetyConfig())
        self.session_db_path = os.path.realpath(session_db_path) if session_db_path else None

    async def execute(self, db_path: str, **kwargs) -> ToolResult:
        """Extract the SQLite schema."""
        if _is_session_db(self.session_db_path, db_path):
            return ToolResult(error="Access to the session database via this tool is not permitted.")

        if not os.path.exists(db_path):
            return ToolResult(error=f"Database file not found: {db_path}")

        conn = None
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cursor = conn.cursor()

            # Fetch table names
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]

            if not tables:
                return ToolResult(content="Database has no tables.")

            output = "Database Schema:\n\n"

            for table in tables:
                safe_table = table.replace('"', '""')
                cursor.execute(f'PRAGMA table_info("{safe_table}");')
                columns = cursor.fetchall()

                output += f"### Table: {table}\n"
                for col in columns:
                    # PRAGMA returns: cid, name, type, notnull, dflt_value, pk
                    col_name = col[1]
                    col_type = col[2]
                    pk = " (PRIMARY KEY)" if col[5] else ""
                    output += f"- {col_name} [{col_type}]{pk}\n"
                output += "\n"

            return ToolResult(content=output.strip())

        except sqlite3.Error as e:
            return ToolResult(error=f"SQLite Error: {e}")
        finally:
            if conn:
                conn.close()
