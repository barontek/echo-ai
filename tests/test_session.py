"""Tests for session management.

Merged from test_session.py and test_session_integration.py.
Integration tests run against a real temporary SQLite database.
"""

import pytest
import sqlite3
import time
from datetime import datetime, timedelta

from src.agentframework.session import (
    Session,
    SessionManager,
    ChangeTracker,
)


# ---------------------------------------------------------------------------
# Session dataclass
# ---------------------------------------------------------------------------


class TestSession:
    """Tests for Session dataclass."""

    def test_create_session(self):
        session = Session(id="test-123")
        assert session.id == "test-123"
        assert isinstance(session.created_at, datetime)
        assert session.messages == []
        assert session.metadata == {}

    def test_session_to_dict(self):
        session = Session(id="test-123")
        session.messages = [{"role": "user", "content": "hello"}]
        session.metadata = {"model": "test"}

        data = session.to_dict()
        assert data["id"] == "test-123"
        assert "created_at" in data
        assert data["messages"] == [{"role": "user", "content": "hello"}]
        assert data["metadata"] == {"model": "test"}

    def test_session_from_dict(self):
        data = {
            "id": "test-456",
            "created_at": "2024-01-01T12:00:00",
            "messages": [{"role": "assistant", "content": "hi"}],
            "metadata": {"key": "value"},
        }
        session = Session.from_dict(data)
        assert session.id == "test-456"
        assert session.messages == [{"role": "assistant", "content": "hi"}]
        assert session.metadata == {"key": "value"}

    def test_session_roundtrip(self):
        original = Session(
            id="roundtrip-test",
            title="My Chat",
            messages=[{"role": "user", "content": "test"}],
            metadata={"version": 1},
        )
        data = original.to_dict()
        restored = Session.from_dict(data)
        assert restored.id == original.id
        assert restored.title == original.title
        assert restored.messages == original.messages
        assert restored.metadata == original.metadata

    def test_to_dict_null_title(self):
        session = Session(id="abc")
        d = session.to_dict()
        assert d["title"] is None
        restored = Session.from_dict(d)
        assert restored.title is None

    def test_from_dict_missing_optional_fields(self):
        data = {"id": "min", "created_at": datetime.now().isoformat()}
        session = Session.from_dict(data)
        assert session.id == "min"
        assert session.title is None
        assert session.messages == []
        assert session.metadata == {}


# ---------------------------------------------------------------------------
# SessionManager (real DB integration tests)
# ---------------------------------------------------------------------------


@pytest.fixture
def session_dir(tmp_path):
    d = tmp_path / "test_sessions"
    d.mkdir()
    return str(d)


@pytest.fixture
def manager(session_dir):
    mgr = SessionManager(session_dir)
    yield mgr
    mgr.close()


class TestSessionManagerCRUD:
    def test_create_and_load(self, manager):
        created = manager.create_session(session_id="s1", title="First Chat")
        assert created.id == "s1"
        assert created.title == "First Chat"

        manager.current_session = None
        loaded = manager.load_session("s1")
        assert loaded is not None
        assert loaded.id == "s1"
        assert loaded.title == "First Chat"

    def test_load_nonexistent_returns_none(self, manager):
        result = manager.load_session("does-not-exist")
        assert result is None
        assert manager.current_session is None

    def test_create_sets_current_session(self, manager):
        assert manager.current_session is None
        manager.create_session(session_id="s1")
        assert manager.current_session is not None
        assert manager.current_session.id == "s1"

    def test_create_with_auto_id(self, manager):
        session = manager.create_session()
        assert session.id is not None
        assert len(session.id) > 0

    def test_create_duplicate_id_overwrites(self, manager):
        manager.create_session(session_id="dup", title="Original")
        manager.create_session(session_id="dup", title="Overwritten")
        manager.current_session = None
        loaded = manager.load_session("dup")
        assert loaded is not None
        assert loaded.title == "Overwritten"

    def test_list_sessions_order(self, manager):
        manager.create_session(session_id="old")
        time.sleep(0.05)
        manager.create_session(session_id="new")
        sessions, total = manager.list_sessions()
        assert len(sessions) == 2
        assert total == 2
        assert sessions[0].id == "new"
        assert sessions[1].id == "old"

    def test_list_sessions_empty(self, manager):
        sessions, total = manager.list_sessions()
        assert sessions == []
        assert total == 0

    def test_list_sessions_pagination(self, manager):
        for i in range(5):
            manager.create_session(session_id=f"session_{i}")
        sessions, total = manager.list_sessions(limit=2, offset=0)
        assert len(sessions) == 2
        assert total == 5
        sessions, total = manager.list_sessions(limit=2, offset=2)
        assert len(sessions) == 2
        assert total == 5

    def test_list_sessions_search(self, manager):
        manager.create_session(session_id="test_alpha", title="Alpha Session")
        manager.create_session(session_id="test_beta", title="Beta Session")
        manager.create_session(session_id="test_gamma", title="Gamma Session")
        sessions, total = manager.list_sessions(search="alpha")
        assert len(sessions) == 1
        assert total == 1
        assert sessions[0].title == "Alpha Session"


class TestMessagePersistence:
    def test_add_message_persists(self, manager):
        manager.create_session(session_id="msg_test")
        manager.add_message("user", "hello")
        manager.add_message("assistant", "hi there")

        manager.current_session = None
        loaded = manager.load_session("msg_test")
        assert loaded is not None
        assert len(loaded.messages) == 2
        assert loaded.messages[0]["role"] == "user"
        assert loaded.messages[0]["content"] == "hello"
        assert loaded.messages[1]["role"] == "assistant"

    def test_add_message_with_metadata(self, manager):
        manager.create_session(session_id="msg-meta-test")
        manager.add_message("user", "Hello", name="test")
        msg = manager.current_session.messages[0]
        assert msg["name"] == "test"

    def test_add_message_no_current_session_is_noop(self, manager):
        manager.current_session = None
        manager.add_message("user", "lost message")
        sessions, total = manager.list_sessions()
        assert sessions == []
        assert total == 0

    def test_save_session_updates_existing(self, manager):
        manager.create_session(session_id="update_test", title="V1")
        manager.current_session.title = "V2"
        manager.current_session.messages = [{"role": "user", "content": "updated"}]
        manager.save_session()

        manager.current_session = None
        loaded = manager.load_session("update_test")
        assert loaded is not None
        assert loaded.title == "V2"
        assert len(loaded.messages) == 1
        sessions, total = manager.list_sessions()
        assert total == 1

    def test_save_session_none_is_noop(self, manager):
        manager.current_session = None
        manager.save_session()  # Should not crash

    def test_get_history_returns_messages(self, manager):
        manager.create_session(session_id="hist")
        manager.add_message("user", "test")
        history = manager.get_history()
        assert len(history) == 1
        assert history[0]["content"] == "test"

    def test_get_history_empty(self, manager):
        assert manager.get_history() == []


class TestPurge:
    def test_purge_all(self, manager):
        manager.create_session(session_id="a")
        manager.create_session(session_id="b")
        manager.create_session(session_id="c")
        count = manager.purge_sessions()
        assert count == 3
        sessions, total = manager.list_sessions()
        assert sessions == []
        assert total == 0
        assert manager.current_session is None

    def test_purge_resets_current_session(self, manager):
        manager.create_session(session_id="active")
        assert manager.current_session is not None
        manager.purge_sessions()
        assert manager.current_session is None

    def test_purge_zero_sessions(self, manager):
        count = manager.purge_sessions()
        assert count == 0

    def test_purge_with_days_filter(self, manager):
        manager.create_session(session_id="old_one")
        conn = sqlite3.connect(str(manager.db_path))
        old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE agent_sessions SET created_at = ? WHERE id = 'old_one'",
            (old_date,),
        )
        conn.commit()
        conn.close()

        manager.create_session(session_id="new_one")
        count = manager.purge_sessions(older_than_days=5)
        assert count == 1
        remaining, total = manager.list_sessions()
        assert len(remaining) == 1
        assert remaining[0].id == "new_one"


class TestPurgeEmpty:
    def test_purge_empty_removes_sessions_without_user_messages(self, manager):
        manager.create_session(session_id="empty1")
        manager.create_session(session_id="empty2")
        manager.create_session(session_id="with_user")
        manager.add_message("user", "hello")

        count = manager.purge_empty_sessions()
        assert count == 2
        remaining, total = manager.list_sessions()
        assert total == 1
        assert remaining[0].id == "with_user"

    def test_purge_empty_keeps_sessions_with_any_user_message(self, manager):
        manager.create_session(session_id="user_only")
        manager.add_message("user", "hello")

        manager.create_session(session_id="mixed")
        manager.add_message("user", "hello")
        manager.add_message("assistant", "hi")

        count = manager.purge_empty_sessions()
        assert count == 0
        assert len(manager.list_sessions()) == 2

    def test_purge_empty_resets_current_if_deleted(self, manager):
        manager.create_session(session_id="empty_to_delete")
        manager.create_session(session_id="keep")
        manager.add_message("user", "hi")
        manager.current_session = manager.load_session("empty_to_delete")

        count = manager.purge_empty_sessions()
        assert count == 1
        assert manager.current_session is None


class TestMigration:
    def test_migration_adds_title_column(self, tmp_path):
        db_dir = tmp_path / "legacy_sessions"
        db_dir.mkdir()
        db_path = db_dir / "agent_sessions.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE agent_sessions (
                id VARCHAR PRIMARY KEY,
                created_at DATETIME,
                messages JSON,
                session_metadata JSON
            )
        """)
        conn.execute(
            "INSERT INTO agent_sessions (id, created_at, messages, session_metadata) VALUES (?, ?, '[]', '{}')",
            ("legacy_session", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        conn.close()

        mgr = SessionManager(str(db_dir))
        sessions, total = mgr.list_sessions()
        assert len(sessions) == 1
        assert total == 1
        assert sessions[0].id == "legacy_session"
        assert sessions[0].title is None
        mgr.close()

    def test_migration_idempotent(self, tmp_path):
        db_dir = tmp_path / "idempotent_test"
        db_dir.mkdir()

        mgr1 = SessionManager(str(db_dir))
        mgr1.create_session(session_id="test", title="Hello")
        mgr1.close()

        mgr2 = SessionManager(str(db_dir))
        sessions, total = mgr2.list_sessions()
        assert len(sessions) == 1
        assert total == 1
        assert sessions[0].title == "Hello"
        mgr2.close()


class TestSessionEdgeCases:
    def test_session_with_empty_messages(self, manager):
        manager.create_session(session_id="empty_msgs")
        manager.current_session = None
        loaded = manager.load_session("empty_msgs")
        assert loaded is not None
        assert loaded.messages == []

    def test_session_with_large_message(self, manager):
        big_content = "x" * 100_000
        manager.create_session(session_id="big")
        manager.add_message("user", big_content)
        manager.current_session = None
        loaded = manager.load_session("big")
        assert loaded is not None
        assert loaded.messages[0]["content"] == big_content

    def test_session_with_special_characters(self, manager):
        special = "Hello 🌍\n\t\"quotes\" 'apostrophe' <html> &amp; ñ"
        manager.create_session(session_id="special")
        manager.add_message("user", special)
        manager.current_session = None
        loaded = manager.load_session("special")
        assert loaded is not None
        assert loaded.messages[0]["content"] == special

    def test_session_metadata_persists(self, manager):
        manager.create_session(session_id="meta")
        manager.current_session.metadata = {"tool_count": 3, "tags": ["test", "debug"]}
        manager.save_session()
        manager.current_session = None
        loaded = manager.load_session("meta")
        assert loaded is not None
        assert loaded.metadata["tool_count"] == 3
        assert loaded.metadata["tags"] == ["test", "debug"]


# ---------------------------------------------------------------------------
# ChangeTracker
# ---------------------------------------------------------------------------


class TestChangeTracker:
    """Tests for ChangeTracker class."""

    @pytest.fixture
    def tracker(self):
        return ChangeTracker()

    def test_record_change(self, tracker):
        tracker.record_change(
            "write", "file.txt", old_content=None, new_content="hello"
        )
        assert len(tracker.changes) == 1
        assert tracker.changes[0]["operation"] == "write"
        assert tracker.changes[0]["path"] == "file.txt"
        assert tracker.changes[0]["old_content"] is None
        assert tracker.changes[0]["new_content"] == "hello"

    def test_undo(self, tracker):
        tracker.record_change("write", "file.txt", new_content="hello")
        change = tracker.undo()
        assert change is not None
        assert change["path"] == "file.txt"
        assert len(tracker.changes) == 0
        assert len(tracker.redo_stack) == 1

    def test_undo_empty(self, tracker):
        assert tracker.undo() is None

    def test_redo(self, tracker):
        tracker.record_change("write", "file.txt", new_content="hello")
        tracker.undo()
        change = tracker.redo()
        assert change is not None
        assert change["path"] == "file.txt"
        assert len(tracker.changes) == 1
        assert len(tracker.redo_stack) == 0

    def test_redo_empty(self, tracker):
        assert tracker.redo() is None

    def test_redo_clears_on_new_change(self, tracker):
        tracker.record_change("write", "file1.txt", new_content="a")
        tracker.undo()
        tracker.record_change("write", "file2.txt", new_content="b")
        assert len(tracker.redo_stack) == 0

    def test_can_undo(self, tracker):
        assert tracker.can_undo() is False
        tracker.record_change("write", "file.txt")
        assert tracker.can_undo() is True

    def test_can_redo(self, tracker):
        assert tracker.can_redo() is False
        tracker.record_change("write", "file.txt")
        tracker.undo()
        assert tracker.can_redo() is True

    def test_multiple_undo_redo(self, tracker):
        tracker.record_change("write", "file1.txt", new_content="a")
        tracker.record_change("write", "file2.txt", new_content="b")
        tracker.record_change("write", "file3.txt", new_content="c")

        assert tracker.undo()["path"] == "file3.txt"
        assert tracker.undo()["path"] == "file2.txt"
        assert tracker.undo()["path"] == "file1.txt"
        assert tracker.undo() is None

        assert tracker.redo()["path"] == "file1.txt"
        assert tracker.redo()["path"] == "file2.txt"
        assert tracker.redo()["path"] == "file3.txt"
        assert tracker.redo() is None
