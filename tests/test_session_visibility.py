"""Test SQLite session visibility between independent SessionManagers.

Reproduces the suspected visibility race between:
1. REST API `POST /api/sessions` → state.agent.session_manager.create_session()
2. WebSocket handler → active_agent.load_session(session_id)

Both use separate SessionManager instances pointing to the same .db file.
"""

import pytest

from src.agentframework.session import SessionManager


@pytest.fixture
def session_dir(tmp_path):
    d = tmp_path / "test_sessions"
    d.mkdir()
    return str(d)


def test_load_created_session_across_managers(session_dir):
    """Simulate: REST API creates session → WS handler loads it."""
    rest_mgr = SessionManager(session_dir)
    ws_mgr = SessionManager(session_dir)
    try:
        session_id = "cross_mgr_test"
        rest_mgr.create_session(session_id=session_id, title="REST-created")

        loaded = ws_mgr.load_session(session_id)

        assert loaded is not None, (
            f"FAIL: Session '{session_id}' created by REST manager was NOT found "
            f"by WS manager — this confirms a SQLite visibility race."
        )
        assert loaded.id == session_id
        assert loaded.title == "REST-created"
        print(
            f"PASS: Session '{session_id}' created by one SessionManager was "
            f"visible to another SessionManager pointing to the same DB."
        )
    finally:
        rest_mgr.close()
        ws_mgr.close()


def test_reverse_direction(session_dir):
    """Symmetry check: create on WS-side, load on REST-side."""
    ws_mgr = SessionManager(session_dir)
    rest_mgr = SessionManager(session_dir)
    try:
        session_id = "reverse_test"
        ws_mgr.create_session(session_id=session_id, title="WS-created")

        loaded = rest_mgr.load_session(session_id)

        assert loaded is not None, (
            f"FAIL: Reverse direction also failed — "
            f"session '{session_id}' not visible across managers."
        )
        assert loaded.id == session_id
        print(
            f"PASS: Reverse direction works — session created by one manager "
            f"visible to the other."
        )
    finally:
        ws_mgr.close()
        rest_mgr.close()


def test_concurrent_create_and_load(session_dir):
    """Stress-test: sequential creates → loads to rule out timing issues."""
    mgr_a = SessionManager(session_dir)
    mgr_b = SessionManager(session_dir)
    try:
        for i in range(10):
            sid = f"concurrent_test_{i}"
            mgr_a.create_session(session_id=sid, title=f"Session {i}")

            loaded = mgr_b.load_session(sid)
            assert loaded is not None, (
                f"FAIL: Session '{sid}' not found on mgr_b after mgr_a created it."
            )
            assert loaded.title == f"Session {i}"

        print(
            f"PASS: All {10} sessions created by mgr_a were visible to mgr_b."
        )
    finally:
        mgr_a.close()
        mgr_b.close()


def test_session_with_messages_visibility(session_dir):
    """Verify messages written by one manager are visible to another."""
    writer = SessionManager(session_dir)
    reader = SessionManager(session_dir)
    try:
        sid = "msg_visibility_test"
        writer.create_session(session_id=sid)
        writer.add_message("user", "Hello from writer")
        writer.add_message("assistant", "Reply from writer")

        loaded = reader.load_session(sid)
        assert loaded is not None, (
            f"FAIL: Session with messages not visible to reader manager."
        )
        assert len(loaded.messages) == 2
        assert loaded.messages[0]["role"] == "user"
        assert loaded.messages[0]["content"] == "Hello from writer"
        assert loaded.messages[1]["role"] == "assistant"
        print(
            f"PASS: Session with messages created by writer manager is "
            f"fully visible to reader manager."
        )
    finally:
        writer.close()
        reader.close()
