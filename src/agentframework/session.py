"""Session management for the agent framework using SQLite."""

import gc
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Boolean, create_engine, text, String, DateTime, LargeBinary, TypeDecorator
from sqlalchemy.orm import declarative_base, sessionmaker, Mapped, mapped_column

from .constants import ECHO_DATA_DIR
from .db_crypto import prompt_for_fernet

logger = logging.getLogger(__name__)

# Process-wide lock serialising all writes to agent_sessions.
# Every write path — SessionManager.save_session / delete_session / purge_* AND
# the change_password re-encryption in routers/unlock.py — must hold this lock.
# The lock is a plain threading.Lock (not RLock) because:
#   - write methods never re-enter each other on the same thread, and
#   - change_password acquires via asyncio.to_thread and releases on the
#     async-event-loop thread, which RLock would not allow.
db_write_lock = threading.Lock()

DEFAULT_SESSION_DIR = str(ECHO_DATA_DIR / "sessions")
DEFAULT_BACKUP_DIR = str(ECHO_DATA_DIR / "sessions" / ".backups")

Base = declarative_base()


class EncryptedJSON(TypeDecorator):
    """SQLAlchemy type that transparently encrypts JSON columns with Fernet.

    The Fernet instance is set on the **class** itself (``_engine_fernet``)
    by :class:`SessionManager` at construction time.  Because there is only
    one active database per process, a single class-level Fernet is correct.
    """

    impl = LargeBinary
    cache_ok = True

    _engine_fernet: Fernet | None = None

    @classmethod
    def _get_fernet(cls) -> Fernet:
        if cls._engine_fernet is None:
            raise RuntimeError(
                "No Fernet instance configured. "
                "Create a SessionManager first."
            )
        return cls._engine_fernet

    def process_bind_param(self, value: object, dialect: object) -> bytes | None:
        if value is None:
            return None
        return self._get_fernet().encrypt(json.dumps(value, default=str).encode("utf-8"))

    def process_result_value(self, value: bytes | None, dialect: object) -> object | None:
        if value is None:
            return None
        try:
            return json.loads(self._get_fernet().decrypt(value).decode("utf-8"))
        except InvalidToken:
            raise ValueError("Incorrect database password") from None


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
            "event_type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionEvent":
        event_type = data.get("event_type") or data.get("type") or "unknown"
        return cls(
            event_type=event_type,
            data=data.get("data", {}),
            timestamp=datetime.fromisoformat(data["timestamp"])
            if data.get("timestamp")
            else None,
        )


class DBSessionModel(Base):
    """SQLAlchemy model for agent sessions."""

    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str | None] = mapped_column(EncryptedJSON, nullable=True)
    title_generation_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    messages: Mapped[list[dict]] = mapped_column(EncryptedJSON, default=list)
    session_metadata: Mapped[dict] = mapped_column(EncryptedJSON, default=dict)
    events: Mapped[list[dict]] = mapped_column(EncryptedJSON, default=list)


@dataclass
class Session:
    """A conversation session."""

    id: str
    title: str | None = None
    title_generation_attempted: bool = False
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

    def __init__(self, session_dir: str | None = None, fernet: Fernet | None = None):
        if session_dir is None:
            session_dir = DEFAULT_SESSION_DIR
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)

        # Configure the Fernet instance on EncryptedJSON
        if fernet is not None:
            EncryptedJSON._engine_fernet = fernet
        elif EncryptedJSON._engine_fernet is None:
            salt_path = self.session_dir / ".db_salt"
            EncryptedJSON._engine_fernet = prompt_for_fernet(salt_path)

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
            conn.execute(text("PRAGMA journal_mode=DELETE"))
            conn.execute(text("PRAGMA synchronous=FULL"))
            conn.execute(text("PRAGMA busy_timeout=5000"))
            conn.commit()
        Base.metadata.create_all(self.engine)
        # Lock down DB and session directory permissions
        os.chmod(str(self.db_path), 0o600)
        os.chmod(str(self.session_dir), 0o700)
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

        # Lightweight migration: add 'title' column if it doesn't exist yet
        self._migrate_add_title_column()
        # Lightweight migration: add 'events' column if it doesn't exist yet
        self._migrate_add_events_column()
        # Lightweight migration: add 'title_generation_attempted' column if it doesn't exist yet
        self._migrate_add_title_generation_attempted_column()
        # Add indexes for faster queries
        self._migrate_add_indexes()
        # Encrypt any plaintext titles left from before V7
        self._migrate_encrypt_titles()

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

    def _migrate_add_title_generation_attempted_column(self) -> None:
        """Add 'title_generation_attempted' column to agent_sessions if missing."""

        def migrate(conn):
            cursor = conn.execute("PRAGMA table_info(agent_sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if "title_generation_attempted" not in columns:
                conn.execute(
                    "ALTER TABLE agent_sessions ADD COLUMN title_generation_attempted BOOLEAN DEFAULT 0"
                )
                conn.commit()
                logger.info("Migrated agent_sessions: added 'title_generation_attempted' column.")

        self._with_connection(migrate, "'title_generation_attempted' column")

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

    def _migrate_encrypt_titles(self) -> None:
        """Encrypt any plaintext titles left from before V7 encryption."""

        def migrate(conn):
            cursor = conn.execute("SELECT id, title FROM agent_sessions")
            rows = cursor.fetchall()
            fernet = EncryptedJSON._get_fernet()
            updated = 0
            for row_id, title in rows:
                if title is None:
                    continue
                if isinstance(title, str):
                    encrypted = fernet.encrypt(
                        json.dumps(title).encode("utf-8")
                    )
                    conn.execute(
                        "UPDATE agent_sessions SET title = ? WHERE id = ?",
                        (encrypted, row_id),
                    )
                    updated += 1
            if updated:
                conn.commit()
                logger.info(
                    "Migrated %d plaintext title(s) to encrypted format.", updated
                )

        self._with_connection(migrate, "'title' encryption")

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
                title_generation_attempted=db_session.title_generation_attempted,  # type: ignore
                created_at=db_session.created_at,  # type: ignore
                messages=db_session.messages or [],  # type: ignore
                metadata=db_session.session_metadata or {},  # type: ignore
                events=db_session.events or [],  # type: ignore
            )
            self.current_session = session
            self.log_event("session_loaded", {"messages_count": len(session.messages)})
            return session

    def save_session(self, session: Session | None = None) -> None:
        """Save the current session properties to the DB (upsert)."""
        if session is None:
            session = self.current_session
        if session is None:
            return

        with db_write_lock:
            with self.SessionLocal() as db:
                db_session = DBSessionModel(
                    id=session.id,
                    title=session.title,
                    title_generation_attempted=session.title_generation_attempted,
                    created_at=session.created_at,
                    messages=session.messages,
                    session_metadata=session.metadata,
                    events=session.events or [],
                )
                db.merge(db_session)
                gc.collect()  # preempt GC before SQLAlchemy C extensions run
                db.commit()

    def truncate_history(self, index: int) -> None:
        """Truncate session history to the given index (exclusive), dropping all subsequent messages."""
        if not self.current_session:
            return

        if index < 0:
            index = 0

        if index >= len(self.current_session.messages):
            return

        self.current_session.messages = self.current_session.messages[:index]
        self.save_session()
        self.log_event("history_truncated", {"index": index})

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
                # Titles are encrypted, so filter in-memory
                all_rows = query.order_by(DBSessionModel.created_at.desc()).all()
                for db_session in all_rows:
                    title = db_session.title  # Decrypted by EncryptedJSON
                    if title and search.lower() in title.lower():
                        sessions.append(
                            Session(
                                id=db_session.id,  # type: ignore
                                title=title,
                                title_generation_attempted=db_session.title_generation_attempted,  # type: ignore
                                created_at=db_session.created_at,  # type: ignore
                                messages=db_session.messages or [],  # type: ignore
                                metadata=db_session.session_metadata or {},  # type: ignore
                                events=db_session.events or [],  # type: ignore
                            )
                        )
                total = len(sessions)
                sessions = sessions[offset : offset + limit]
            else:
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
                            title_generation_attempted=db_session.title_generation_attempted,  # type: ignore
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
        else:
            logger.warning("Cannot add message: no active session")

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

    def delete_session(self, session_id: str) -> None:
        """Delete a single session by ID."""
        with db_write_lock:
            with self.SessionLocal() as db:
                db.query(DBSessionModel).filter(DBSessionModel.id == session_id).delete(synchronize_session=False)
                db.commit()
                if self.current_session and self.current_session.id == session_id:
                    self.current_session = None

    def purge_sessions(self, older_than_days: int | None = None) -> int:
        """Purge old sessions from the database."""
        with db_write_lock:
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
        to_delete: list[str] = []
        with db_write_lock:
            with self.SessionLocal() as db:
                for db_session in db.query(DBSessionModel).yield_per(100):
                    messages = db_session.messages or []
                    has_user_message = any(
                        isinstance(m, dict) and m.get("role") == "user" for m in messages
                    )
                    if not has_user_message:
                        to_delete.append(db_session.id)

                for sid in to_delete:
                    db.query(DBSessionModel).filter(DBSessionModel.id == sid).delete()
                db.commit()
                count = len(to_delete)

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
        previous = self.current_session
        session = self.load_session(session_id)
        self.current_session = previous
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

        # Check for duplicate
        existing = self.load_session(data["id"])
        self.current_session = existing  # restore if load changed it
        if existing:
            raise ValueError(f"Session {data['id']} already exists")

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

    def __del__(self) -> None:
        """Try to clean up the engine pool on garbage collection."""
        if hasattr(self, "engine") and self.engine is not None:
            try:
                with self.engine.connect() as conn:
                    conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
                    conn.commit()
                self.engine.dispose()
            except Exception:
                pass

    def close(self) -> None:
        """Dispose of the database engine and any connections in its pool.

        Runs a final WAL checkpoint before closing to ensure no sidecar
        files linger with stale data.
        """
        if hasattr(self, "engine") and self.engine is not None:
            try:
                with self.engine.connect() as conn:
                    conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
                    conn.commit()
                self.engine.dispose()
                logger.debug("Successfully disposed of SQLAlchemy engine.")
            except Exception as e:
                logger.error("Failed to dispose of SQLAlchemy engine: %s", e)
            self.engine = None

    def __enter__(self) -> "SessionManager":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class ChangeTracker:
    """Track file changes for undo functionality with memory-safe large file handling."""

    LARGE_FILE_THRESHOLD = 50000

    def __init__(self, backup_dir: str | None = None, session_id: str = "default"):
        if backup_dir is None:
            backup_dir = DEFAULT_BACKUP_DIR
        self.changes: list[dict] = []
        self.redo_stack: list[dict] = []
        # Use per-session subdirectory to avoid cross-session undo corruption
        self.backup_dir = Path(backup_dir) / session_id
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _store_large_content(self, content: str | None) -> str | None:
        """Store content > 50K to temp file, return filepath instead of raw content."""
        if content and len(content) > self.LARGE_FILE_THRESHOLD:
            filepath = self.backup_dir / f"{uuid.uuid4().hex}.txt"
            try:
                filepath.write_text(content, encoding="utf-8")
                return str(filepath)
            except Exception as e:
                logger.warning("Failed to write large content to backup: %s", e)
                return content
        return content

    def _read_content(self, content: str | None) -> str | None:
        """Read content from memory or from backup file if filepath detected."""
        if content is None:
            return None
        content_path = Path(content)
        if content_path.is_file() and content_path.parent == self.backup_dir:
            try:
                return content_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("Failed to read backup file %s: %s", content, e)
                return content  # Fall back to the path string
        return content

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
                "old_content": self._store_large_content(old_content),
                "new_content": self._store_large_content(new_content),
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
        for change in reverted:
            change["old_content"] = self._read_content(change.get("old_content"))
            change["new_content"] = self._read_content(change.get("new_content"))
        return reverted

    def undo(self) -> dict | None:
        """Undo the last change."""
        if not self.changes:
            return None

        change = self.changes.pop()
        change["old_content"] = self._read_content(change.get("old_content"))
        change["new_content"] = self._read_content(change.get("new_content"))
        self.redo_stack.append(change)
        return change

    def redo(self) -> dict | None:
        """Redo the last undone change."""
        if not self.redo_stack:
            return None

        change = self.redo_stack.pop()
        change["old_content"] = self._read_content(change.get("old_content"))
        change["new_content"] = self._read_content(change.get("new_content"))
        self.changes.append(change)
        return change

    def can_undo(self) -> bool:
        return len(self.changes) > 0

    def can_redo(self) -> bool:
        return len(self.redo_stack) > 0
