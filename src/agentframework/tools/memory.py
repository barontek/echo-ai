"""Memory tool for storing and retrieving personal facts across sessions."""

import sqlite3
import logging
from pathlib import Path

from pydantic import BaseModel

from . import Tool, ToolResult
from ..safety import SafetyConfig, SecurityValidator

logger = logging.getLogger(__name__)


class MemoryParams(BaseModel):
    """Parameters for MemoryTool."""

    action: str
    query: str = ""
    category: str = "fact"


class MemoryTool(Tool):
    """Store and retrieve personal facts using SQLite."""

    parameters_model = MemoryParams

    def __init__(
        self,
        db_path: str | Path | None = None,
        safety_config: SafetyConfig | None = None,
    ):
        super().__init__(
            name="memory",
            description=(
                "Store and retrieve personal facts about the user across sessions. "
                "Actions: "
                "'save_fact' to remember a piece of information (provide content in 'query', optional 'category' like 'personal', 'preference', 'fact'); "
                "'recall_fact' to search memory by keyword (provide search terms in 'query'); "
                "'list_facts' to list all stored memories, optionally filtered by 'category'; "
                "'delete_fact' to delete a specific memory by providing the exact content in 'query' (IMPORTANT: always confirm with the user before calling this); "
                "'clear_facts' to delete all memories, optionally filtered by 'category' (IMPORTANT: always confirm with the user before calling this)."
            ),
        )

        self.validator: SecurityValidator
        if safety_config:
            self.validator = SecurityValidator(safety_config)
        else:
            self.validator = SecurityValidator(SafetyConfig())

        if db_path is None:
            home = str(Path.home())
            self.db_path = Path(home) / ".agent_memory" / "memory.db"
        else:
            self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _recreate_db(self) -> None:
        """Recreate the database if it's corrupted."""
        logger.warning(f"Recreating corrupted database at {self.db_path}")
        self.db_path.unlink(missing_ok=True)
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

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at DESC)"
        )

        # Create FTS5 virtual table
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content,
                category,
                content='memories',
                content_rowid='id'
            )
        """)

        # Create triggers to keep FTS table in sync
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content, category)
                VALUES (new.id, new.content, new.category);
            END;
        """)
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, category)
                VALUES ('delete', old.id, old.content, old.category);
            END;
        """)
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, category)
                VALUES ('delete', old.id, old.content, old.category);
                INSERT INTO memories_fts(rowid, content, category)
                VALUES (new.id, new.content, new.category);
            END;
        """)

        # Check if we need to backfill FTS index
        cursor.execute("SELECT COUNT(*) FROM memories")
        memories_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM memories_fts")
        fts_count = cursor.fetchone()[0]

        if memories_count > 0 and fts_count == 0:
            cursor.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")

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
        elif action == "list_facts":
            return await self._list_facts(category if query == "" else query)
        elif action == "delete_fact":
            return await self._delete_fact(query)
        elif action == "clear_facts":
            return await self._clear_facts(category)
        else:
            return ToolResult(error=f"Unknown action: {action}")

    async def _save_fact(self, content: str, category: str) -> ToolResult:
        """Save a fact to memory."""
        try:
            # Extract key info for search
            query_text = content.lower().strip()

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Prevent exact duplicates
            cursor.execute(
                "SELECT id FROM memories WHERE content = ? AND category = ?",
                (content, category),
            )
            if cursor.fetchone():
                conn.close()
                return ToolResult(content=f"Already remembered: {content}")

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
            if not search_query.strip():
                return ToolResult(
                    content="I don't have any memories matching that query yet."
                )

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 1. FTS5 Search
            safe_terms = []
            for term in search_query.split():
                clean_term = "".join(c for c in term if c.isalnum())
                if clean_term:
                    safe_terms.append(clean_term)

            results = []

            if safe_terms:
                fts_query = " OR ".join(safe_terms)
                cursor.execute(
                    """
                    SELECT m.content, m.category
                    FROM memories_fts f
                    JOIN memories m ON m.id = f.rowid
                    WHERE memories_fts MATCH ?
                    ORDER BY rank
                    LIMIT 5
                    """,
                    (fts_query,),
                )
                results.extend(cursor.fetchall())

            # 2. LIKE search fallback
            # This handles CJK characters or substrings that FTS skips
            if len(results) < 5:
                search_terms = search_query.lower().split()
                seen_contents = set(row[0] for row in results)

                for term in search_terms:
                    cursor.execute(
                        "SELECT content, category FROM memories WHERE query_text LIKE ? ORDER BY created_at DESC LIMIT 5",
                        (f"%{term}%",),
                    )
                    for row in cursor.fetchall():
                        if row[0] not in seen_contents:
                            results.append(row)
                            seen_contents.add(row[0])
                        if len(results) >= 5:
                            break
                    if len(results) >= 5:
                        break

            conn.close()

            if not results:
                return ToolResult(
                    content="I don't have any memories matching that query yet."
                )

            formatted = []
            for content, category in results[:5]:  # Cap at 5 total
                formatted.append(f"[{category}] {content}")

            return ToolResult(content="\n".join(formatted))
        except Exception as e:
            return ToolResult(error=f"Failed to recall: {str(e)}")

    async def _list_facts(self, category_filter: str = "") -> ToolResult:
        """List all stored facts, optionally filtered by category."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            if category_filter and category_filter != "fact":
                cursor.execute(
                    "SELECT content, category FROM memories WHERE category = ? ORDER BY created_at DESC",
                    (category_filter,),
                )
            else:
                cursor.execute(
                    "SELECT content, category FROM memories ORDER BY category, created_at DESC"
                )

            results = cursor.fetchall()
            conn.close()

            if not results:
                return ToolResult(content="No memories stored yet.")

            formatted = [f"[{category}] {content}" for content, category in results]
            return ToolResult(content="\n".join(formatted))
        except Exception as e:
            return ToolResult(error=f"Failed to list facts: {str(e)}")

    def load_memories(self, categories: list[str] | None = None) -> str:
        """Load all stored memories as a formatted string for injection into system context.

        Args:
            categories: Optional list of categories to filter by. If None, all memories are loaded.

        Returns:
            Formatted string of memories, or empty string if none exist.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            if categories:
                placeholders = ",".join("?" * len(categories))
                cursor.execute(
                    f"SELECT content, category FROM memories WHERE category IN ({placeholders}) ORDER BY category, created_at DESC",  # nosec B608
                    categories,
                )
            else:
                cursor.execute(
                    "SELECT content, category FROM memories ORDER BY category, created_at DESC"
                )

            results = cursor.fetchall()
            conn.close()

            if not results:
                return ""

            lines = [f"[{category}] {content}" for content, category in results]
            return "\n".join(lines)
        except Exception:
            return ""

    async def _delete_fact(self, content: str) -> ToolResult:
        """Delete a specific memory by matching content (exact or partial)."""
        try:
            if not content.strip():
                return ToolResult(
                    error="Please provide the content of the memory to delete."
                )

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Try exact match first, then fall back to partial
            cursor.execute(
                "SELECT id, content, category FROM memories WHERE content = ?",
                (content,),
            )
            rows = cursor.fetchall()

            if not rows:
                # Try case-insensitive partial match
                cursor.execute(
                    "SELECT id, content, category FROM memories WHERE LOWER(content) LIKE ?",
                    (f"%{content.lower()}%",),
                )
                rows = cursor.fetchall()

            if not rows:
                conn.close()
                return ToolResult(content=f"No memory found matching: {content}")

            # Request approval before deleting
            preview = "\n".join(f"[{cat}] {cont}" for _, cont, cat in rows)
            if self.validator.requires_approval("memory"):
                approved = self.validator.get_approval(
                    "memory", f"Delete {len(rows)} memory(s):\n{preview}"
                )
                if not approved:
                    conn.close()
                    return ToolResult(error="Memory deletion requires approval")

            deleted = []
            for row_id, row_content, row_category in rows:
                cursor.execute("DELETE FROM memories WHERE id = ?", (row_id,))
                deleted.append(f"[{row_category}] {row_content}")

            conn.commit()
            conn.close()

            summary = "\n".join(deleted)
            return ToolResult(content=f"Deleted {len(deleted)} memory(s):\n{summary}")
        except sqlite3.DatabaseError:
            self._recreate_db()
            return ToolResult(
                content="Memory database was corrupted and has been reset."
            )
        except Exception as e:
            return ToolResult(error=f"Failed to delete: {str(e)}")

    async def _clear_facts(self, category: str = "") -> ToolResult:
        """Delete all memories, optionally filtering by category."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Count before deletion for the summary
            if category and category != "fact":
                cursor.execute(
                    "SELECT COUNT(*) FROM memories WHERE category = ?", (category,)
                )
            else:
                cursor.execute("SELECT COUNT(*) FROM memories")
            count = cursor.fetchone()[0]

            if count == 0:
                conn.close()
                return ToolResult(content="No memories to clear.")

            # Request approval before clearing
            scope = (
                f"category '{category}'"
                if (category and category != "fact")
                else "all categories"
            )
            if self.validator.requires_approval("memory"):
                approved = self.validator.get_approval(
                    "memory", f"Clear {count} memory(s) from {scope}"
                )
                if not approved:
                    conn.close()
                    return ToolResult(error="Memory clear requires approval")

            if category and category != "fact":
                cursor.execute("DELETE FROM memories WHERE category = ?", (category,))
                msg = f"Cleared {count} memory(s) from category '{category}'."
            else:
                cursor.execute("DELETE FROM memories")
                # Also rebuild the FTS index so it reflects the empty table
                cursor.execute(
                    "INSERT INTO memories_fts(memories_fts) VALUES('rebuild')"
                )
                msg = f"Cleared all {count} memory(s)."

            conn.commit()
            conn.close()
            return ToolResult(content=msg)
        except sqlite3.DatabaseError:
            self._recreate_db()
            return ToolResult(
                content="Memory database was corrupted and has been reset. All memories have been cleared."
            )
        except Exception as e:
            return ToolResult(error=f"Failed to clear: {str(e)}")
