"""Session management for the agent framework."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Session:
    """A conversation session."""

    id: str
    created_at: datetime = field(default_factory=datetime.now)
    messages: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "messages": self.messages,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        return cls(
            id=data["id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            messages=data.get("messages", []),
            metadata=data.get("metadata", {}),
        )


class SessionManager:
    """Manages agent sessions."""

    def __init__(self, session_dir: str = ".agent_sessions"):
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(exist_ok=True)
        self.current_session: Session | None = None

    def create_session(self, session_id: str | None = None) -> Session:
        """Create a new session."""
        if session_id is None:
            session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        session = Session(id=session_id)
        self.current_session = session
        return session

    def load_session(self, session_id: str) -> Session | None:
        """Load an existing session."""
        session_path = self.session_dir / f"{session_id}.json"
        if not session_path.exists():
            return None
        
        with open(session_path) as f:
            data = json.load(f)
            session = Session.from_dict(data)
            self.current_session = session
            return session

    def save_session(self, session: Session | None = None) -> None:
        """Save the current session."""
        if session is None:
            session = self.current_session
        if session is None:
            return
        
        session_path = self.session_dir / f"{session.id}.json"
        with open(session_path, "w") as f:
            json.dump(session.to_dict(), f, indent=2)

    def list_sessions(self) -> list[Session]:
        """List all saved sessions."""
        sessions = []
        for path in self.session_dir.glob("*.json"):
            with open(path) as f:
                data = json.load(f)
                sessions.append(Session.from_dict(data))
        return sorted(sessions, key=lambda s: s.created_at, reverse=True)

    def add_message(self, role: str, content: str, **kwargs) -> None:
        """Add a message to the current session."""
        if self.current_session:
            msg = {"role": role, "content": content, **kwargs}
            self.current_session.messages.append(msg)
            self.save_session()

    def get_history(self) -> list[dict[str, Any]]:
        """Get message history."""
        if self.current_session:
            return self.current_session.messages
        return []


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
