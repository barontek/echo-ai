"""Memory tool for storing and retrieving personal facts across sessions."""

import sqlite3
from pathlib import Path

from pydantic import BaseModel

from . import Tool, ToolResult


class MemoryParams(BaseModel):
    """Parameters for MemoryTool."""

    action: str
    query: str = ""
    category: str = "fact"


class MemoryTool(Tool):
    """Store and retrieve personal facts using SQLite."""

    parameters_model = MemoryParams

    def __init__(self, db_path: str | Path | None = None):
        super().__init__(
            name="memory",
            description="Store and retrieve personal facts about you. Use save_fact to remember information, and recall_fact to search your memory.",
        )

        if db_path is None:
            home = str(Path.home())
            self.db_path = Path(home) / ".agent_memory" / "memory.db"
        else:
            self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the SQLite database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_text TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'fact',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    async def execute(
        self, action: str, query: str = "", category: str = "fact", **kwargs
    ) -> ToolResult:
        """Execute memory action."""
        if action == "save_fact":
            return await self._save_fact(query, category)
        elif action == "recall_fact":
            return await self._recall_fact(query)
        else:
            return ToolResult(error=f"Unknown action: {action}")

    async def _save_fact(self, content: str, category: str) -> ToolResult:
        """Save a fact to memory."""
        try:
            # Extract key info for search
            query_text = content.lower().strip()

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO memories (query_text, content, category) VALUES (?, ?, ?)",
                (query_text, content, category),
            )
            conn.commit()
            conn.close()

            return ToolResult(content=f"Remembered: {content}")
        except Exception as e:
            return ToolResult(error=f"Failed to save: {str(e)}")

    async def _recall_fact(self, search_query: str) -> ToolResult:
        """Search memory for relevant facts."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Simple text search using LIKE
            search_terms = search_query.lower().split()
            results = []

            for term in search_terms:
                cursor.execute(
                    "SELECT content, category FROM memories WHERE query_text LIKE ? ORDER BY created_at DESC LIMIT 5",
                    (f"%{term}%",),
                )
                for row in cursor.fetchall():
                    if row not in results:
                        results.append(row)

            conn.close()

            if not results:
                return ToolResult(
                    content="I don't have any memories matching that query yet."
                )

            formatted = []
            for content, category in results[:5]:
                formatted.append(f"[{category}] {content}")

            return ToolResult(content="\n".join(formatted))
        except Exception as e:
            return ToolResult(error=f"Failed to recall: {str(e)}")
