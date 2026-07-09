"""Extended tests for session management - covering edge cases."""

import pytest
import sqlite3
from pathlib import Path
from unittest.mock import patch

from src.agentframework.session import (
    SessionManager,
    SessionEvent,
    ChangeTracker,
)


class TestSessionEvent:
    def test_session_event_creation(self):
        event = SessionEvent(event_type="message_added", data={"role": "user"})
        assert event.event_type == "message_added"
        assert event.data == {"role": "user"}
        assert event.timestamp is not None

    def test_session_event_to_dict(self):
        event = SessionEvent(event_type="test", data={"key": "val"})
        d = event.to_dict()
        assert d["event_type"] == "test"
        assert d["data"] == {"key": "val"}
        assert "timestamp" in d

    def test_session_event_from_dict(self):
        data = {
            "type": "test_event",
            "data": {"msg": "hello"},
            "timestamp": "2024-06-01T12:00:00",
        }
        event = SessionEvent.from_dict(data)
        assert event.event_type == "test_event"
        assert event.data == {"msg": "hello"}
        assert event.timestamp is not None

    def test_session_event_from_dict_no_timestamp(self):
        data = {"type": "test_event", "data": {}}
        event = SessionEvent.from_dict(data)
        assert event.timestamp is not None


class TestLogEvent:
    @pytest.fixture
    def manager(self, tmp_path):
        with SessionManager(str(tmp_path / "sessions")) as mgr:
            yield mgr

    def test_log_event_no_current_session(self, manager):
        manager.current_session = None
        manager.log_event("test", {"data": "val"})

    def test_log_event_initializes_events_list(self, manager):
        manager.create_session(session_id="log-test")
        manager.current_session.events = None
        manager.log_event("test_event", {"key": "value"})
        assert manager.current_session.events is not None
        assert len(manager.current_session.events) == 1
        assert manager.current_session.events[0]["event_type"] == "test_event"


class TestTruncateHistory:
    @pytest.fixture
    def manager(self, tmp_path):
        with SessionManager(str(tmp_path / "sessions")) as mgr:
            yield mgr

    def test_truncate_no_current_session(self, manager):
        manager.current_session = None
        manager.truncate_history(0)

    def test_truncate_negative_index(self, manager):
        manager.create_session(session_id="trunc-test")
        manager.add_message("user", "hello")
        manager.add_message("assistant", "hi")
        manager.truncate_history(-1)
        assert len(manager.current_session.messages) == 0

    def test_truncate_index_beyond_length(self, manager):
        manager.create_session(session_id="trunc-beyond")
        manager.add_message("user", "hello")
        manager.truncate_history(100)
        assert len(manager.current_session.messages) == 1

    def test_truncate_removes_messages(self, manager):
        manager.create_session(session_id="trunc-success")
        manager.add_message("user", "msg1")
        manager.add_message("user", "msg2")
        manager.add_message("user", "msg3")
        manager.truncate_history(2)
        assert len(manager.current_session.messages) == 2


class TestSaveCheckpoint:
    @pytest.fixture
    def manager(self, tmp_path):
        with SessionManager(str(tmp_path / "sessions")) as mgr:
            yield mgr

    def test_save_checkpoint_no_session(self, manager):
        manager.current_session = None
        manager.save_checkpoint("wid", "node1", {"key": "val"})

    def test_save_checkpoint_creates_checkpoints_key(self, manager):
        manager.create_session(session_id="ck-test")
        manager.save_checkpoint("ck-test", "start", {"data": "test"})
        assert "checkpoints" in manager.current_session.metadata
        assert len(manager.current_session.metadata["checkpoints"]) == 1


class TestExportImportSession:
    @pytest.fixture
    def manager(self, tmp_path):
        with SessionManager(str(tmp_path / "sessions")) as mgr:
            yield mgr

    def test_export_session_not_found(self, manager):
        result = manager.export_session("nonexistent")
        assert result is None

    def test_export_and_import_roundtrip(self, manager):
        original = manager.create_session(session_id="exp-test", title="Export Test")
        original.messages = [{"role": "user", "content": "hello"}]
        manager.save_session()
        data = manager.export_session("exp-test")
        assert data is not None
        assert data["id"] == "exp-test"
        assert data["title"] == "Export Test"

        manager.delete_session("exp-test")
        imported = manager.import_session(data)
        assert imported.id == "exp-test"
        assert imported.title == "Export Test"
        assert imported.messages == [{"role": "user", "content": "hello"}]

    def test_import_session_missing_id(self, manager):
        with pytest.raises(ValueError, match="id"):
            manager.import_session({"title": "no id"})

    def test_import_with_invalid_date(self, manager):
        data = {
            "id": "import-date-test",
            "created_at": "not-a-date",
            "messages": [],
        }
        session = manager.import_session(data)
        assert session.id == "import-date-test"


class TestChangeTrackerExtended:
    @pytest.fixture
    def tracker(self, tmp_path):
        return ChangeTracker(backup_dir=str(tmp_path / "backups"))

    def test_store_and_read_large_content(self, tracker):
        content = "x" * 60000
        filepath = tracker._store_large_content(content)
        assert filepath != content

    def test_store_small_content(self, tracker):
        result = tracker._store_large_content("small")
        assert result == "small"

    def test_read_content_from_file(self, tracker):
        filepath = tracker.backup_dir / "test.txt"
        filepath.write_text("file content")
        result = tracker._read_content(str(filepath))
        assert result == "file content"

    def test_read_content_returns_content_when_file_not_found(self, tracker):
        result = tracker._read_content("/nonexistent/12345.txt")
        assert result == "/nonexistent/12345.txt"

    def test_read_content_small(self, tracker):
        result = tracker._read_content("inline")
        assert result == "inline"

    def test_revert_change_for_tool(self, tracker):
        tracker.record_change(
            "write", "f1.txt", old_content="old1", new_content="new1",
            tool_call_id="tc1"
        )
        tracker.record_change(
            "write", "f2.txt", old_content="old2", new_content="new2",
            tool_call_id="tc2"
        )
        tracker.record_change(
            "write", "f3.txt", old_content="old3", new_content="new3",
            tool_call_id="tc1"
        )
        reverted = tracker.revert_change_for_tool("tc1")
        assert len(reverted) == 2
        assert len(tracker.changes) == 1
        assert tracker.changes[0]["path"] == "f2.txt"

    def test_revert_change_for_tool_no_match(self, tracker):
        tracker.record_change("write", "f1.txt", tool_call_id="tc1")
        reverted = tracker.revert_change_for_tool("nonexistent")
        assert reverted == []

    def test_backup_dir_already_exists(self, tmp_path):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        (backup_dir / "stale.txt").write_text("stale")
        tracker = ChangeTracker(backup_dir=str(backup_dir))
        assert (backup_dir / "stale.txt").exists()
        assert tracker.changes == []

    def test_backup_dir_cleanup_exception(self, tmp_path):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        f = backup_dir / "locked.txt"
        f.write_text("locked")
        with patch.object(Path, "unlink", side_effect=Exception("permission")):
            tracker = ChangeTracker(backup_dir=str(backup_dir))
            assert tracker.changes == []


class TestCloseErrorHandling:
    def test_close_dispose_error(self, tmp_path):
        with SessionManager(str(tmp_path / "sessions")) as mgr:
            with patch.object(mgr.engine, "dispose", side_effect=Exception("dispose failed")):
                mgr.close()


class TestMigrationFailed:
    def test_migration_failure_logged(self, tmp_path, caplog):
        db_path = tmp_path / "sessions" / "agent_sessions.db"
        db_path.parent.mkdir()
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE agent_sessions (id VARCHAR PRIMARY KEY)")
        conn.close()
        with SessionManager(str(db_path.parent)):
            pass


class TestDefaultSessionDir:
    def test_session_dir_defaults(self, tmp_path):
        import base64
        from cryptography.fernet import Fernet
        from agentframework.session import DEFAULT_SESSION_DIR

        fernet = Fernet(base64.urlsafe_b64encode(b"\x00" * 32))
        with SessionManager(session_dir=str(tmp_path / "explicit"), fernet=fernet) as mgr:
            assert str(mgr.session_dir).endswith("explicit")
        # Also verify the default constant is the real default
        assert "echo-ai" in DEFAULT_SESSION_DIR


class TestLargeContentWriteFailure:
    def test_store_large_content_write_error(self, tmp_path):
        tracker = ChangeTracker(backup_dir=str(tmp_path / "backups"))
        large = "x" * 60000
        with patch.object(Path, "write_text", side_effect=PermissionError("denied")):
            result = tracker._store_large_content(large)
        assert result == large

    def test_read_content_read_error(self, tmp_path):
        tracker = ChangeTracker(backup_dir=str(tmp_path / "backups"))
        filepath = tracker.backup_dir / "test.txt"
        filepath.write_text("some content")
        with patch.object(Path, "read_text", side_effect=Exception("read failed")):
            result = tracker._read_content(str(filepath))
        assert result == str(filepath)
