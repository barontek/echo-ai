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

class DBSessionModel(Base):
    """SQLAlchemy model for agent sessions."""
    __tablename__ = 'agent_sessions'

    id = Column(String, primary_key=True)
    title = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    messages = Column(JSON, default=list)
    session_metadata = Column(JSON, default=dict)

@dataclass
class Session:
    """A conversation session."""

    id: str
    title: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    messages: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "messages": self.messages,
            "metadata": self.metadata,
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
        )


class SessionManager:
    """Manages agent sessions using SQLite backends."""

    def __init__(self, session_dir: str = ".agent_sessions"):
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(exist_ok=True)

        # Initialize SQLite database connection
        self.db_path = self.session_dir / "agent_sessions.db"
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        # Lightweight migration: add 'title' column if it doesn't exist yet
        self._migrate_add_title_column()

        self.current_session: Session | None = None

    def _migrate_add_title_column(self) -> None:
        """Add the 'title' column to agent_sessions if it's missing (pre-existing DBs)."""
        import sqlite3
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.execute("PRAGMA table_info(agent_sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if "title" not in columns:
                conn.execute("ALTER TABLE agent_sessions ADD COLUMN title TEXT")
                conn.commit()
                logger.info("Migrated agent_sessions: added 'title' column.")
            conn.close()
        except Exception as e:
            logger.error("Migration check for 'title' column failed: %s", e)

    def create_session(self, session_id: str | None = None, title: str | None = None) -> Session:
        """Create a new session."""
        if session_id is None:
            session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        session = Session(id=session_id, title=title)
        self.current_session = session
        self.save_session(session)
        return session

    def load_session(self, session_id: str) -> Session | None:
        """Load an existing session from the DB."""
        with self.SessionLocal() as db:
            db_session = db.query(DBSessionModel).filter(DBSessionModel.id == session_id).first()
            if not db_session:
                return None

            session = Session(
                id=db_session.id,  # type: ignore
                title=db_session.title,  # type: ignore
                created_at=db_session.created_at,  # type: ignore
                messages=db_session.messages,  # type: ignore
                metadata=db_session.session_metadata  # type: ignore
            )
            self.current_session = session
            return session

    def save_session(self, session: Session | None = None) -> None:
        """Save the current session properties to the DB."""
        if session is None:
            session = self.current_session
        if session is None:
            return

        with self.SessionLocal() as db:
            db_session = db.query(DBSessionModel).filter(DBSessionModel.id == session.id).first()
            if not db_session:
                db_session = DBSessionModel(
                    id=session.id,
                    title=session.title,
                    created_at=session.created_at,
                    messages=session.messages,
                    session_metadata=session.metadata
                )
                db.add(db_session)
            else:
                # SQLAlchemy JSON columns sometimes need explicit flagging if mutated in place
                # To be safe, reassign the dict/list natively
                db.query(DBSessionModel).filter(DBSessionModel.id == session.id).update({
                    "title": session.title,
                    "messages": session.messages,
                    "session_metadata": session.metadata
                })
            db.commit()

    def list_sessions(self) -> list[Session]:
        """List all saved sessions sorted by recency."""
        sessions = []
        with self.SessionLocal() as db:
            for db_session in db.query(DBSessionModel).order_by(DBSessionModel.created_at.desc()).all():
                sessions.append(Session(
                    id=db_session.id,  # type: ignore
                    title=db_session.title,  # type: ignore
                    created_at=db_session.created_at,  # type: ignore
                    messages=db_session.messages,  # type: ignore
                    metadata=db_session.session_metadata  # type: ignore
                ))
        return sessions

    def add_message(self, role: str, content: str, **kwargs) -> None:
        """Add a message to the current session and persist to DB."""
        if self.current_session:
            msg = {"role": role, "content": content, **kwargs}
            self.current_session.messages.append(msg)
            self.save_session()

    def save_checkpoint(self, workflow_id: str, current_node: str, state: dict) -> None:
        """Save a state checkout for workflow graphs."""
        if self.current_session and self.current_session.id == workflow_id:
            if "checkpoints" not in self.current_session.metadata:
                self.current_session.metadata["checkpoints"] = []

            self.current_session.metadata["checkpoints"].append({
                "node": current_node,
                "state": state,
                "timestamp": datetime.now().isoformat()
            })
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
                exists = db.query(DBSessionModel).filter(DBSessionModel.id == self.current_session.id).first()
                if not exists:
                    self.current_session = None

            return count

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

    def record_change(self, operation: str, path: str, old_content: str | None = None, new_content: str | None = None):
        """Record a file change."""
        self.changes.append({
            "operation": operation,
            "path": path,
            "old_content": old_content,
            "new_content": new_content,
            "timestamp": datetime.now().isoformat(),
        })
        self.redo_stack.clear()

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
