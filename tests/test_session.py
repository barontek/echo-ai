"""Tests for session management."""

import pytest
import tempfile
from datetime import datetime

from src.agentframework.session import (
    Session,
    SessionManager,
    ChangeTracker,
)


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
        original = Session(id="roundtrip-test")
        original.messages = [{"role": "user", "content": "test"}]
        original.metadata = {"version": 1}

        data = original.to_dict()
        restored = Session.from_dict(data)

        assert restored.id == original.id
        assert restored.messages == original.messages
        assert restored.metadata == original.metadata


class TestSessionManager:
    """Tests for SessionManager class."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def manager(self, temp_dir):
        return SessionManager(session_dir=temp_dir)

    def test_create_session(self, manager):
        session = manager.create_session("my-session")
        assert session.id == "my-session"
        assert manager.current_session == session

    def test_create_session_auto_id(self, manager):
        session = manager.create_session()
        assert session.id is not None
        assert len(session.id) > 0

    def test_save_and_load_session(self, manager, temp_dir):
        session = manager.create_session("save-test")
        session.messages = [{"role": "user", "content": "hello"}]
        manager.save_session()

        loaded = manager.load_session("save-test")
        assert loaded is not None
        assert loaded.id == "save-test"
        assert loaded.messages == [{"role": "user", "content": "hello"}]

    def test_load_nonexistent_session(self, manager):
        result = manager.load_session("does-not-exist")
        assert result is None

    def test_list_sessions(self, manager, temp_dir):
        manager.create_session("session-1")
        manager.save_session()

        manager.create_session("session-2")
        manager.save_session()

        sessions = manager.list_sessions()
        assert len(sessions) >= 2

    def test_add_message(self, manager):
        manager.create_session("msg-test")
        manager.add_message("user", "Hello")

        assert len(manager.current_session.messages) == 1
        assert manager.current_session.messages[0]["role"] == "user"
        assert manager.current_session.messages[0]["content"] == "Hello"

    def test_add_message_with_metadata(self, manager):
        manager.create_session("msg-meta-test")
        manager.add_message("user", "Hello", name="test")

        msg = manager.current_session.messages[0]
        assert msg["name"] == "test"

    def test_get_history(self, manager):
        manager.create_session("history-test")
        manager.add_message("user", "First")
        manager.add_message("assistant", "Second")

        history = manager.get_history()
        assert len(history) == 2
        assert history[0]["content"] == "First"
        assert history[1]["content"] == "Second"

    def test_get_history_no_session(self, manager):
        assert manager.get_history() == []


class TestChangeTracker:
    """Tests for ChangeTracker class."""

    @pytest.fixture
    def tracker(self):
        return ChangeTracker()

    def test_record_change(self, tracker):
        tracker.record_change("write", "file.txt", old_content=None, new_content="hello")

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
        result = tracker.undo()
        assert result is None

    def test_redo(self, tracker):
        tracker.record_change("write", "file.txt", new_content="hello")
        tracker.undo()
        change = tracker.redo()

        assert change is not None
        assert change["path"] == "file.txt"
        assert len(tracker.changes) == 1
        assert len(tracker.redo_stack) == 0

    def test_redo_empty(self, tracker):
        result = tracker.redo()
        assert result is None

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
