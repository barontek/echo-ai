"""Session management for the agent framework using SQLite."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, Column, String, DateTime, JSON
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

Base = declarative_base()


class SessionEvent:
    """An event in the session event log for audit/replay."""

    def __init__(
        self,
        event_type: str,
        data: dict | None = None,
        timestamp: datetime | None = None,
    ):
        self.event_type = event_type
        self.data = data or {}
        self.timestamp = timestamp or datetime.now()

    def to_dict(self) -> dict:
        return {
            "type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionEvent":
        return cls(
            event_type=data["type"],
            data=data.get("data", {}),
            timestamp=datetime.fromisoformat(data["timestamp"])
            if data.get("timestamp")
            else None,
        )


class DBSessionModel(Base):
    """SQLAlchemy model for agent sessions."""

    __tablename__ = "agent_sessions"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    messages = Column(JSON, default=list)
    session_metadata = Column(JSON, default=dict)
    events = Column(JSON, default=list)


@dataclass
class Session:
    """A conversation session."""

    id: str
    title: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    messages: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat()
            if isinstance(self.created_at, datetime)
            else self.created_at,
            "messages": self.messages,
            "metadata": self.metadata,
            "events": self.events,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        created_at = data["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        return cls(
            id=data["id"],
            title=data.get("title"),
            created_at=created_at,
            messages=data.get("messages", []),
            metadata=data.get("metadata", {}),
            events=data.get("events", []),
        )


class SessionManager:
    """Manages agent sessions using SQLite backends."""

    def __init__(self, session_dir: str = ".agent_sessions"):
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(exist_ok=True)

        # Initialize SQLite database connection with pooling
        self.db_path = self.session_dir / "agent_sessions.db"
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        with self.engine.connect() as conn:
            from sqlalchemy import text

            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA synchronous=NORMAL"))
            conn.execute(text("PRAGMA busy_timeout=5000"))
            conn.commit()
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

        # Lightweight migration: add 'title' column if it doesn't exist yet
        self._migrate_add_title_column()
        # Lightweight migration: add 'events' column if it doesn't exist yet
        self._migrate_add_events_column()
        # Add indexes for faster queries
        self._migrate_add_indexes()

        self.current_session: Session | None = None

    def _with_connection(self, operation, operation_name: str) -> None:
        """Execute a database operation with a connection.

        Args:
            operation: A callable that takes a sqlite3 connection and performs the operation.
            operation_name: Human-readable name for logging.
        """
        import sqlite3

        conn = None
        try:
            conn = sqlite3.connect(str(self.db_path))
            operation(conn)
        except Exception as e:
            logger.error("Migration %s failed: %s", operation_name, e)
        finally:
            if conn:
                conn.close()

    def _migrate_add_title_column(self) -> None:
        """Add the 'title' column to agent_sessions if it's missing (pre-existing DBs)."""

        def migrate(conn):
            cursor = conn.execute("PRAGMA table_info(agent_sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if "title" not in columns:
                conn.execute("ALTER TABLE agent_sessions ADD COLUMN title TEXT")
                conn.commit()
                logger.info("Migrated agent_sessions: added 'title' column.")

        self._with_connection(migrate, "'title' column")

    def _migrate_add_events_column(self) -> None:
        """Add the 'events' column to agent_sessions if it's missing (pre-existing DBs)."""

        def migrate(conn):
            cursor = conn.execute("PRAGMA table_info(agent_sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if "events" not in columns:
                conn.execute(
                    "ALTER TABLE agent_sessions ADD COLUMN events TEXT DEFAULT '[]'"
                )
                conn.commit()
                logger.info("Migrated agent_sessions: added 'events' column.")

        self._with_connection(migrate, "'events' column")

    def _migrate_add_indexes(self) -> None:
        """Add indexes for faster queries."""

        def migrate(conn):
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_sessions_created_at "
                "ON agent_sessions(created_at DESC)"
            )
            conn.commit()
            logger.info("Migrated agent_sessions: added indexes.")

        self._with_connection(migrate, "indexes")

    def log_event(self, event_type: str, data: dict | None = None) -> None:
        """Log an event to the session's event log."""
        if not self.current_session:
            return
        if self.current_session.events is None:
            self.current_session.events = []
        event = SessionEvent(event_type, data).to_dict()
        self.current_session.events.append(event)
        logger.debug(
            "session_event_logged",
            extra={"session_id": self.current_session.id, "event_type": event_type},
        )

    def create_session(
        self, session_id: str | None = None, title: str | None = None
    ) -> Session:
        """Create a new session."""
        if session_id is None:
            session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        session = Session(id=session_id, title=title, events=[])
        self.current_session = session
        self.save_session(session)
        self.log_event("session_created", {"title": title})
        return session

    def load_session(self, session_id: str) -> Session | None:
        """Load an existing session from the DB."""
        with self.SessionLocal() as db:
            db_session = (
                db.query(DBSessionModel).filter(DBSessionModel.id == session_id).first()
            )
            if not db_session:
                return None

            session = Session(
                id=db_session.id,  # type: ignore
                title=db_session.title,  # type: ignore
                created_at=db_session.created_at,  # type: ignore
                messages=db_session.messages or [],  # type: ignore
                metadata=db_session.session_metadata or {},  # type: ignore
                events=db_session.events or [],  # type: ignore
            )
            self.current_session = session
            self.log_event("session_loaded", {"messages_count": len(session.messages)})
            return session

    def save_session(self, session: Session | None = None) -> None:
        """Save the current session properties to the DB."""
        if session is None:
            session = self.current_session
        if session is None:
            return

        with self.SessionLocal() as db:
            db_session = (
                db.query(DBSessionModel).filter(DBSessionModel.id == session.id).first()
            )
            if not db_session:
                db_session = DBSessionModel(
                    id=session.id,
                    title=session.title,
                    created_at=session.created_at,
                    messages=session.messages,
                    session_metadata=session.metadata,
                    events=session.events or [],
                )
                db.add(db_session)
            else:
                db.query(DBSessionModel).filter(DBSessionModel.id == session.id).update(
                    {
                        "title": session.title,
                        "messages": session.messages,
                        "session_metadata": session.metadata,
                        "events": session.events or [],
                    }
                )
            db.commit()

    def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
    ) -> tuple[list["Session"], int]:
        """List saved sessions with pagination.

        Args:
            limit: Maximum number of sessions to return
            offset: Number of sessions to skip
            search: Optional search term for session titles

        Returns:
            Tuple of (sessions list, total count)
        """
        sessions = []
        with self.SessionLocal() as db:
            query = db.query(DBSessionModel)

            if search:
                query = query.filter(DBSessionModel.title.ilike(f"%{search}%"))

            total = query.count()

            for db_session in (
                query.order_by(DBSessionModel.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            ):
                sessions.append(
                    Session(
                        id=db_session.id,  # type: ignore
                        title=db_session.title,  # type: ignore
                        created_at=db_session.created_at,  # type: ignore
                        messages=db_session.messages or [],  # type: ignore
                        metadata=db_session.session_metadata or {},  # type: ignore
                        events=db_session.events or [],  # type: ignore
                    )
                )
        return sessions, total

    def add_message(self, role: str, content: str, **kwargs) -> None:
        """Add a message to the current session and persist to DB."""
        if self.current_session:
            msg = {"role": role, "content": content, **kwargs}
            self.current_session.messages.append(msg)
            self.log_event(
                "message_added", {"role": role, "content_length": len(content)}
            )
            self.save_session()

    def add_tool_results_to_last_assistant(self, tool_results: list[dict]) -> None:
        """Attach tool results to the last assistant message's tool_calls."""
        if not self.current_session or not tool_results:
            return

        # Find last assistant message with tool_calls (go backwards)
        for i in range(len(self.current_session.messages) - 1, -1, -1):
            msg = self.current_session.messages[i]
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                # Attach each result to its corresponding tool_call
                tool_calls = msg["tool_calls"]
                for result in tool_results:
                    tc_id = result.get("tool_call_id")
                    for tc in tool_calls:
                        # Check both new and old format for id
                        tc_id_found = tc.get("id") or tc.get("function", {}).get("id")
                        if tc_id_found == tc_id:
                            tc["result"] = {
                                "content": result.get("content"),
                                "error": result.get("error"),
                            }
                            break
                self.log_event(
                    "tool_results_attached",
                    {"count": len(tool_results)},
                )
                self.save_session()
                return

    def save_checkpoint(self, workflow_id: str, current_node: str, state: dict) -> None:
        """Save a state checkout for workflow graphs."""
        if self.current_session and self.current_session.id == workflow_id:
            if "checkpoints" not in self.current_session.metadata:
                self.current_session.metadata["checkpoints"] = []

            self.current_session.metadata["checkpoints"].append(
                {
                    "node": current_node,
                    "state": state,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            self.save_session()

    def get_history(self) -> list[dict[str, Any]]:
        """Get message history."""
        if self.current_session:
            return self.current_session.messages
        return []

    def purge_sessions(self, older_than_days: int | None = None) -> int:
        """Purge old sessions from the database."""
        with self.SessionLocal() as db:
            query = db.query(DBSessionModel)
            if older_than_days is not None:
                from datetime import timedelta

                cutoff = datetime.now() - timedelta(days=older_than_days)
                query = query.filter(DBSessionModel.created_at < cutoff)

            count = query.count()
            query.delete(synchronize_session=False)
            db.commit()

            # If current session was deleted, reset it
            if self.current_session:
                exists = (
                    db.query(DBSessionModel)
                    .filter(DBSessionModel.id == self.current_session.id)
                    .first()
                )
                if not exists:
                    self.current_session = None

            return count

    def purge_empty_sessions(self) -> int:
        """Purge sessions that have no user messages.

        Returns:
            Number of sessions deleted.
        """
        count = 0
        with self.SessionLocal() as db:
            for db_session in db.query(DBSessionModel).all():
                messages = db_session.messages or []
                has_user_message = any(
                    isinstance(m, dict) and m.get("role") == "user" for m in messages
                )
                if not has_user_message:
                    db.delete(db_session)
                    count += 1

            db.commit()

            if self.current_session:
                exists = (
                    db.query(DBSessionModel)
                    .filter(DBSessionModel.id == self.current_session.id)
                    .first()
                )
                if not exists:
                    self.current_session = None

        return count

    def export_session(self, session_id: str) -> dict | None:
        """Export a session to a dictionary for JSON serialization.

        Args:
            session_id: The session ID to export.

        Returns:
            Dictionary with session data, or None if not found.
        """
        session = self.load_session(session_id)
        if not session:
            return None

        return {
            "id": session.id,
            "title": session.title,
            "created_at": session.created_at.isoformat()
            if session.created_at
            else None,
            "messages": session.messages,
            "metadata": session.metadata,
            "events": session.events,
            "exported_at": datetime.now().isoformat(),
        }

    def import_session(self, data: dict) -> Session:
        """Import a session from a dictionary.

        Args:
            data: Dictionary with session data (from export_session).

        Returns:
            The imported session.

        Raises:
            ValueError: If data is missing required fields.
        """
        if "id" not in data:
            raise ValueError("Missing required field: id")

        import_date = datetime.now()
        if data.get("created_at"):
            try:
                import_date = datetime.fromisoformat(data["created_at"])
            except ValueError:
                pass

        session = Session(
            id=data["id"],
            title=data.get("title", "Imported Session"),
            created_at=import_date,
            messages=data.get("messages", []),
            metadata=data.get("metadata", {}),
            events=data.get("events", []),
        )
        self.save_session(session)
        self.log_event("session_imported", {"original_id": data.get("id")})
        return session

    def close(self) -> None:
        """Dispose of the database engine and any connections in its pool."""
        if hasattr(self, "engine") and self.engine:
            try:
                self.engine.dispose()
                logger.debug("Successfully disposed of SQLAlchemy engine.")
            except Exception as e:
                logger.error("Failed to dispose of SQLAlchemy engine: %s", e)


class ChangeTracker:
    """Track file changes for undo functionality."""

    def __init__(self):
        self.changes: list[dict] = []
        self.redo_stack: list[dict] = []

    def record_change(
        self,
        operation: str,
        path: str,
        old_content: str | None = None,
        new_content: str | None = None,
        tool_call_id: str | None = None,
    ):
        """Record a file change with optional tool_call_id for per-tool tracking."""
        self.changes.append(
            {
                "operation": operation,
                "path": path,
                "old_content": old_content,
                "new_content": new_content,
                "tool_call_id": tool_call_id,
                "timestamp": datetime.now().isoformat(),
            }
        )
        self.redo_stack.clear()

    def revert_change_for_tool(self, tool_call_id: str) -> list[dict]:
        """Revert all changes associated with a specific tool_call_id.

        Returns list of reverted changes for logging purposes.
        """
        reverted: list[dict] = []
        remaining: list[dict] = []

        for change in self.changes:
            if change.get("tool_call_id") == tool_call_id:
                reverted.append(change)
                self.redo_stack.append(change)
            else:
                remaining.append(change)

        self.changes = remaining
        return reverted

    def undo(self) -> dict | None:
        """Undo the last change."""
        if not self.changes:
            return None

        change = self.changes.pop()
        self.redo_stack.append(change)
        return change

    def redo(self) -> dict | None:
        """Redo the last undone change."""
        if not self.redo_stack:
            return None

        change = self.redo_stack.pop()
        self.changes.append(change)
        return change

    def can_undo(self) -> bool:
        return len(self.changes) > 0

    def can_redo(self) -> bool:
        return len(self.redo_stack) > 0
