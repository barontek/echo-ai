"""Tool for querying local SQLite databases."""

import sqlite3
import os
from pydantic import BaseModel, Field

from ..safety import SafetyConfig, SecurityValidator
from . import Tool, ToolResult


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

    def __init__(self, safety_config: SafetyConfig | None = None):
        super().__init__(
            name="sqlite_query",
            description="Execute read-only SQL queries (SELECT) against a local SQLite database. Ensure you use the schema tool first to understand the tables.",
        )
        if safety_config:
            self.validator = SecurityValidator(safety_config)
        else:
            self.validator = SecurityValidator(SafetyConfig(require_approval_for=["sqlite_query"]))

    async def execute(self, db_path: str, query: str, **kwargs) -> ToolResult:
        """Execute the SQLite query."""
        if self.validator.requires_approval("sqlite_query"):
            approved = await self.validator.get_approval_async(
                "sqlite_query", f"Querying {db_path}:\n{query}"
            )
            if not approved:
                return ToolResult(error="Database query requires approval")

        if not os.path.exists(db_path):
            return ToolResult(error=f"Database file not found: {db_path}")

        # Basic guardrail against destructive queries
        query_upper = query.upper().strip()
        forbidden = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "REPLACE"]
        if any(query_upper.startswith(f) for f in forbidden):
            return ToolResult(error="Only read-only SELECT queries are permitted.")

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

    def __init__(self, safety_config: SafetyConfig | None = None):
        super().__init__(
            name="sqlite_schema",
            description="Extract the table schema and column definitions from a local SQLite database file.",
        )
        # Schema reads are generally safe so we don't strictly require approval by default
        self.validator = SecurityValidator(safety_config or SafetyConfig())

    async def execute(self, db_path: str, **kwargs) -> ToolResult:
        """Extract the SQLite schema."""
        if not os.path.exists(db_path):
            return ToolResult(error=f"Database file not found: {db_path}")

        conn = None
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Fetch table names
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]

            if not tables:
                return ToolResult(content="Database has no tables.")

            output = "Database Schema:\n\n"

            for table in tables:
                cursor.execute(f"PRAGMA table_info({table});")
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
