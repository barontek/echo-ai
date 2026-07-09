"""Tests for POST /api/change-password — re-encrypting all sessions under a new key.

Design invariant: there is NO recovery/bypass path.  Forgetting the current
password means data is permanently inaccessible.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from src.agentframework.routers.unlock import derive_key
from src.agentframework.web_api import app
import src.agentframework.web_api as web_api
from src.agentframework.session import set_fernet

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path, password: str, salt: bytes) -> tuple[Path, Fernet]:
    """Create a real sqlite DB with two encrypted sessions.  Returns (db_path, fernet)."""
    key = derive_key(password, salt)
    fernet = Fernet(key)

    db_path = tmp_path / "agent_sessions.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """CREATE TABLE agent_sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            title_generation_attempted INTEGER DEFAULT 0,
            created_at DATETIME,
            messages BLOB,
            session_metadata BLOB,
            events BLOB
        )"""
    )
    for sid, msgs, meta, evts in [
        ("s1", [{"role": "user", "content": "hello"}], {"key": "val"}, [{"type": "created"}]),
        ("s2", [{"role": "assistant", "content": "hi"}], {}, []),
    ]:
        conn.execute(
            """INSERT INTO agent_sessions (id, messages, session_metadata, events, created_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (
                sid,
                fernet.encrypt(json.dumps(msgs, default=str).encode("utf-8")),
                fernet.encrypt(json.dumps(meta, default=str).encode("utf-8")),
                fernet.encrypt(json.dumps(evts, default=str).encode("utf-8")),
            ),
        )
    conn.commit()
    conn.close()
    return db_path, fernet


def _patch_session_dir(tmp_path: Path):
    """Return a context manager that patches _session_dir to *tmp_path*."""
    return patch("src.agentframework.routers.unlock._session_dir", return_value=tmp_path)


# ---------------------------------------------------------------------------
# Autouse fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_state():
    web_api._rate_limiter.clear()
    state = web_api.get_state()
    if state.agent is not None:
        try:
            if hasattr(state.agent, 'close'):
                state.agent.close()
            if hasattr(state.agent, 'session_manager') and state.agent.session_manager:
                state.agent.session_manager.close()
        except Exception:
            pass
    state.agent = None
    state.fernet = None
    state.fernet_key = None
    state.current_session_id = None
    state.message_history = []
    yield
    state.agent = None
    state.fernet = None
    state.fernet_key = None


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestChangePasswordSuccess:
    def test_correct_password_re_encrypts_and_old_password_stops_working(self, tmp_path):
        salt = b"\xaa" * 16
        (tmp_path / ".db_salt").write_bytes(salt)
        db_path, fernet = _make_db(tmp_path, "oldpassword", salt)

        state = web_api.get_state()
        state.agent = MagicMock()
        state.fernet = fernet
        state.fernet_key = derive_key("oldpassword", salt)
        set_fernet(fernet)

        with _patch_session_dir(tmp_path):
            resp = client.post("/api/change-password", json={
                "current_password": "oldpassword",
                "new_password": "newpassword",
                "confirm": "newpassword",
            })

        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "password_changed"

        new_salt = (tmp_path / ".db_salt").read_bytes()
        assert new_salt != salt
        assert len(new_salt) == 16

        # New Fernet in memory matches new key
        new_key = derive_key("newpassword", new_salt)
        new_fernet = Fernet(new_key)
        assert state.fernet_key == new_key

        # Old password rejected
        state.fernet = None
        set_fernet(None)
        with _patch_session_dir(tmp_path):
            unlock_resp = client.post("/api/unlock", json={"password": "oldpassword"})
        assert unlock_resp.status_code == 401, unlock_resp.text

        # New password accepted
        state.fernet = None
        set_fernet(None)
        with _patch_session_dir(tmp_path):
            unlock_resp = client.post("/api/unlock", json={"password": "newpassword"})
        assert unlock_resp.status_code == 200, unlock_resp.text

        # Data still decryptable with new key
        set_fernet(new_fernet)
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT messages FROM agent_sessions WHERE id = 's1'").fetchone()
        assert row is not None
        msgs = json.loads(new_fernet.decrypt(row[0]).decode("utf-8"))
        assert msgs[0]["content"] == "hello"
        conn.close()

    def test_empty_db_still_succeeds(self, tmp_path):
        salt = b"\xbb" * 16
        (tmp_path / ".db_salt").write_bytes(salt)
        key = derive_key("pwd", salt)
        fernet = Fernet(key)

        db_path = tmp_path / "agent_sessions.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE agent_sessions (id TEXT PRIMARY KEY, messages BLOB, session_metadata BLOB, events BLOB, created_at DATETIME)")
        conn.commit()
        conn.close()

        state = web_api.get_state()
        state.agent = MagicMock()
        state.fernet = fernet
        state.fernet_key = key
        set_fernet(fernet)

        with _patch_session_dir(tmp_path):
            resp = client.post("/api/change-password", json={
                "current_password": "pwd",
                "new_password": "newpwd123",
                "confirm": "newpwd123",
            })
        assert resp.status_code == 200, resp.text
        new_salt = (tmp_path / ".db_salt").read_bytes()
        assert new_salt != salt
        assert len(new_salt) == 16


# ---------------------------------------------------------------------------
# Rejection cases
# ---------------------------------------------------------------------------


class TestChangePasswordRejected:
    def test_wrong_current_password_returns_401(self, tmp_path):
        salt = b"\xcc" * 16
        (tmp_path / ".db_salt").write_bytes(salt)
        key = derive_key("realpwd", salt)
        fernet = Fernet(key)
        _make_db(tmp_path, "realpwd", salt)

        state = web_api.get_state()
        state.agent = MagicMock()
        state.fernet = fernet
        state.fernet_key = key
        set_fernet(fernet)

        with _patch_session_dir(tmp_path):
            resp = client.post("/api/change-password", json={
                "current_password": "wrongpwd",
                "new_password": "newpwd123",
                "confirm": "newpwd123",
            })
        assert resp.status_code == 401
        assert "incorrect" in resp.json()["detail"].lower()

    def test_mismatched_new_passwords_returns_400(self, tmp_path):
        salt = b"\xdd" * 16
        (tmp_path / ".db_salt").write_bytes(salt)
        key = derive_key("oldpwd", salt)
        fernet = Fernet(key)
        _make_db(tmp_path, "oldpwd", salt)

        state = web_api.get_state()
        state.agent = MagicMock()
        state.fernet = fernet
        state.fernet_key = key
        set_fernet(fernet)

        with _patch_session_dir(tmp_path):
            resp = client.post("/api/change-password", json={
                "current_password": "oldpwd",
                "new_password": "newpwd",
                "confirm": "different",
            })
        assert resp.status_code == 400
        assert "do not match" in resp.json()["detail"].lower()

    def test_short_new_password_returns_400(self, tmp_path):
        salt = b"\xee" * 16
        (tmp_path / ".db_salt").write_bytes(salt)
        key = derive_key("oldpwd", salt)
        fernet = Fernet(key)

        state = web_api.get_state()
        state.agent = MagicMock()
        state.fernet = fernet
        state.fernet_key = key
        set_fernet(fernet)

        with _patch_session_dir(tmp_path):
            resp = client.post("/api/change-password", json={
                "current_password": "oldpwd",
                "new_password": "short",
                "confirm": "short",
            })
        assert resp.status_code == 400
        assert "8 characters" in resp.json()["detail"]

    def test_locked_session_returns_423(self, tmp_path):
        state = web_api.get_state()
        state.agent = None
        state.fernet = None

        with _patch_session_dir(tmp_path):
            resp = client.post("/api/change-password", json={
                "current_password": "x",
                "new_password": "yyyyyyyy",
                "confirm": "yyyyyyyy",
            })
        assert resp.status_code == 423
        assert "locked" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Transaction rollback safety
# ---------------------------------------------------------------------------


class TestChangePasswordRollbackSafety:
    def test_db_write_failure_does_not_corrupt_db(self, tmp_path):
        """Simulate a DB write error partway through re-encryption and confirm
        the old password still works and the salt file is untouched."""
        salt = b"\xff" * 16
        salt_path = tmp_path / ".db_salt"
        salt_path.write_bytes(salt)

        key = derive_key("original", salt)
        original_fernet = Fernet(key)

        db_path = tmp_path / "agent_sessions.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(
            """CREATE TABLE agent_sessions (
                id TEXT PRIMARY KEY, title TEXT,
                messages BLOB, session_metadata BLOB, events BLOB, created_at DATETIME
            )"""
        )
        conn.execute(
            "INSERT INTO agent_sessions (id, messages, session_metadata, events, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (
                "s1",
                original_fernet.encrypt(json.dumps([{"role": "user"}]).encode("utf-8")),
                original_fernet.encrypt(json.dumps({}).encode("utf-8")),
                original_fernet.encrypt(json.dumps([]).encode("utf-8")),
            ),
        )
        conn.execute(
            "INSERT INTO agent_sessions (id, messages, session_metadata, events, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (
                "s2",
                original_fernet.encrypt(json.dumps([{"role": "assistant"}]).encode("utf-8")),
                original_fernet.encrypt(json.dumps({"k": "v"}).encode("utf-8")),
                original_fernet.encrypt(json.dumps([]).encode("utf-8")),
            ),
        )
        conn.commit()
        conn.close()

        state = web_api.get_state()
        state.agent = MagicMock()
        state.fernet = original_fernet
        state.fernet_key = key
        set_fernet(original_fernet)

        salt_mtime_before = salt_path.stat().st_mtime_ns

        # Patch Fernet.decrypt to fail on the 3rd call (mid-way through row 2)
        import cryptography.fernet as cf
        original_fernet_decrypt = cf.Fernet.decrypt
        decrypt_call_count = 0

        def flaky_decrypt(self, ciphertext):
            nonlocal decrypt_call_count
            decrypt_call_count += 1
            if decrypt_call_count >= 3:
                raise RuntimeError("Simulated re-encryption failure")
            return original_fernet_decrypt(self, ciphertext)

        with _patch_session_dir(tmp_path), patch.object(
            cf.Fernet, "decrypt", flaky_decrypt,
        ):
            resp = client.post("/api/change-password", json={
                "current_password": "original",
                "new_password": "newpwd123",
                "confirm": "newpwd123",
            })

        assert resp.status_code == 500
        assert "Re-encryption failed" in resp.json()["detail"]

        # Salt file untouched
        assert salt_path.stat().st_mtime_ns == salt_mtime_before
        assert salt_path.read_bytes() == salt

        # Old password still works
        state.fernet = None
        set_fernet(None)
        with _patch_session_dir(tmp_path):
            unlock_resp = client.post("/api/unlock", json={"password": "original"})
        assert unlock_resp.status_code == 200, unlock_resp.text

        # DB rows still decryptable with old key
        set_fernet(original_fernet)
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT messages FROM agent_sessions WHERE id = 's1'"
        ).fetchone()
        msgs = json.loads(original_fernet.decrypt(row[0]).decode("utf-8"))
        assert msgs[0]["role"] == "user"
        conn.close()


# ---------------------------------------------------------------------------
# Concurrency safety
# ---------------------------------------------------------------------------


class TestChangePasswordConcurrency:
    """Verify that a concurrent chat write and change_password are serialised
    by db_write_lock — no row can be left encrypted with a mismatched key."""

    def test_concurrent_chat_write_does_not_corrupt_db(self, tmp_path):
        """A SessionManager.save_session call concurrent with change_password
        is serialised by db_write_lock, so no row ends up encrypted with a
        mismatched key.  All rows must be decryptable with the new Fernet
        after both operations complete, and data from the concurrent write
        must not be lost."""
        import threading
        import time

        salt = b"\xaa" * 16
        (tmp_path / ".db_salt").write_bytes(salt)
        db_path, fernet = _make_db(tmp_path, "oldpwd", salt)

        # Add a third session so re-encryption has more work to do,
        # increasing the chance of a true overlap.
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO agent_sessions (id, messages, session_metadata, events, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (
                "s3",
                fernet.encrypt(json.dumps([{"role": "user", "content": "third"}]).encode("utf-8")),
                fernet.encrypt(json.dumps({}).encode("utf-8")),
                fernet.encrypt(json.dumps([]).encode("utf-8")),
            ),
        )
        conn.commit()
        conn.close()

        state = web_api.get_state()
        state.agent = MagicMock()
        state.fernet = fernet
        state.fernet_key = derive_key("oldpwd", salt)
        set_fernet(fernet)

        chat_errors: list[str] = []
        chat_done = threading.Event()

        def do_chat_write() -> None:
            try:
                from src.agentframework.session import SessionManager

                sm = SessionManager(str(tmp_path), fernet=fernet)
                # Brief pause so change_password can acquire the lock first
                time.sleep(0.03)
                sm.create_session("concurrent_session")
                sm.add_message("user", "hello from concurrent write")
                sm.close()
            except Exception as e:
                chat_errors.append(str(e))
            finally:
                chat_done.set()

        t = threading.Thread(target=do_chat_write, daemon=True)
        t.start()
        time.sleep(0.02)  # Let the thread begin initialising the SessionManager

        with _patch_session_dir(tmp_path):
            resp = client.post(
                "/api/change-password",
                json={
                    "current_password": "oldpwd",
                    "new_password": "newpwd123",
                    "confirm": "newpwd123",
                },
            )

        chat_done.wait(timeout=15)

        assert resp.status_code == 200, resp.text
        assert not chat_errors, f"Concurrent chat write failed: {chat_errors}"

        # All data must be decryptable with the NEW key
        new_salt = (tmp_path / ".db_salt").read_bytes()
        new_key = derive_key("newpwd123", new_salt)
        new_fernet = Fernet(new_key)

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT id, messages FROM agent_sessions"
        ).fetchall()
        assert len(rows) >= 4, f"Expected ≥4 sessions, got {len(rows)}"

        for row_id, msg_raw in rows:
            try:
                messages = json.loads(new_fernet.decrypt(msg_raw).decode("utf-8"))
                assert isinstance(messages, list)
            except Exception as exc:
                pytest.fail(f"Row {row_id} not decryptable with new key: {exc}")

        # Concurrent chat session exists with correct content
        row = conn.execute(
            "SELECT messages FROM agent_sessions WHERE id = 'concurrent_session'"
        ).fetchone()
        assert row is not None, "Concurrent chat session not found in DB"
        msgs = json.loads(new_fernet.decrypt(row[0]).decode("utf-8"))
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "hello from concurrent write"
        conn.close()

    def test_multiple_concurrent_writes_are_serialised(self, tmp_path):
        """Fire several chat writes from separate threads alongside
        change_password — all writes must be serialised so no row
        ends up in a mixed key state."""
        import threading
        import time

        salt = b"\xdd" * 16
        (tmp_path / ".db_salt").write_bytes(salt)
        db_path, fernet = _make_db(tmp_path, "secret", salt)

        state = web_api.get_state()
        state.agent = MagicMock()
        state.fernet = fernet
        state.fernet_key = derive_key("secret", salt)
        set_fernet(fernet)

        from src.agentframework.session import SessionManager

        n_writers = 4
        chat_errors: list[str] = []
        writers_remaining = threading.Semaphore(0)

        def writer(n: int) -> None:
            try:
                sm = SessionManager(str(tmp_path), fernet=fernet)
                # Stagger the writes so at least one overlaps with
                # change_password.
                time.sleep(0.01 * n)
                sid = f"concurrent_writer_{n}"
                sm.create_session(sid)
                sm.add_message("user", f"write from writer {n}")
                sm.close()
            except Exception as e:
                chat_errors.append(str(e))
            finally:
                writers_remaining.release()

        threads = [
            threading.Thread(target=writer, args=(n,), daemon=True)
            for n in range(n_writers)
        ]
        for t in threads:
            t.start()

        # Fire change_password while writes are in flight
        time.sleep(0.01)
        with _patch_session_dir(tmp_path):
            resp = client.post(
                "/api/change-password",
                json={
                    "current_password": "secret",
                    "new_password": "moresecret",
                    "confirm": "moresecret",
                },
            )

        for t in threads:
            t.join(timeout=15)

        assert resp.status_code == 200, resp.text
        assert not chat_errors, f"Concurrent writes failed: {chat_errors}"

        # Verify everything decryptable with new key
        new_salt = (tmp_path / ".db_salt").read_bytes()
        new_key = derive_key("moresecret", new_salt)
        new_fernet = Fernet(new_key)

        conn = sqlite3.connect(str(db_path))
        for row_id, msg_raw in conn.execute(
            "SELECT id, messages FROM agent_sessions"
        ).fetchall():
            try:
                msgs = json.loads(new_fernet.decrypt(msg_raw).decode("utf-8"))
                assert isinstance(msgs, list)
            except Exception as exc:
                pytest.fail(f"Row {row_id} not decryptable with new key: {exc}")

        for n in range(n_writers):
            row = conn.execute(
                "SELECT messages FROM agent_sessions WHERE id = ?",
                (f"concurrent_writer_{n}",),
            ).fetchone()
            assert row is not None, f"Writer {n} session not found"
        conn.close()