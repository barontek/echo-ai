"""Tests for database crypto key derivation and Fernet integration."""

from __future__ import annotations

import os
import sqlite3
import stat
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from cryptography.fernet import Fernet, InvalidToken

from src.agentframework.db_crypto import (
    derive_key,
    get_or_create_salt,
    prompt_for_fernet,
    recover_salt_transition,
)


class TestDeriveKey:
    def test_same_password_same_salt_produces_same_key(self):
        salt = b"\x00" * 16
        key1 = derive_key("hunter2", salt)
        key2 = derive_key("hunter2", salt)
        assert key1 == key2

    def test_different_passwords_produce_different_keys(self):
        salt = b"\x00" * 16
        key1 = derive_key("password-a", salt)
        key2 = derive_key("password-b", salt)
        assert key1 != key2

    def test_different_salts_produce_different_keys(self):
        key1 = derive_key("secret", b"\xaa" * 16)
        key2 = derive_key("secret", b"\xbb" * 16)
        assert key1 != key2

    def test_empty_password_is_accepted(self):
        key = derive_key("", b"\x02" * 16)
        assert len(key) > 0

    def test_unicode_password(self):
        key = derive_key("pässwörd 🔑", b"\x03" * 16)
        assert len(key) > 0

    def test_output_is_valid_fernet_key(self):
        key = derive_key("test", b"\x01" * 16)
        fernet = Fernet(key)
        token = fernet.encrypt(b"hello")
        assert fernet.decrypt(token) == b"hello"


class TestFernetRoundTrip:
    def test_same_key_round_trips(self):
        salt = b"\xee" * 16
        k1 = derive_key("opensesame", salt)
        k2 = derive_key("opensesame", salt)
        f = Fernet(k1)
        token = f.encrypt(b"secret data")
        assert Fernet(k2).decrypt(token) == b"secret data"

    def test_wrong_password_raises_invalid_token(self):
        salt = b"\xee" * 16
        correct = derive_key("opensesame", salt)
        wrong = derive_key("wrongpassword", salt)
        token = Fernet(correct).encrypt(b"secret data")
        with pytest.raises(InvalidToken):
            Fernet(wrong).decrypt(token)


class TestGetOrCreateSalt:
    def test_creates_new_salt_file_with_600_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            salt_path = Path(tmp) / "salt.bin"
            salt = get_or_create_salt(salt_path)
            assert salt_path.exists()
            assert len(salt) == 17, f"expected 17 (v2: version+16), got {len(salt)}"
            assert salt[0] == 2, f"expected version byte 0x02, got {salt[0]}"
            mode = stat.S_IMODE(salt_path.stat().st_mode)
            assert mode == 0o600, f"expected 0o600, got {oct(mode)}"

    def test_returns_existing_salt_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            salt_path = Path(tmp) / "salt.bin"
            salt_path.write_bytes(b"\xff" * 16)
            salt = get_or_create_salt(salt_path)
            assert salt == b"\xff" * 16

    def test_different_calls_produce_different_salts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            s1 = get_or_create_salt(Path(tmpdir) / "s1.bin")
            s2 = get_or_create_salt(Path(tmpdir) / "s2.bin")
            assert s1 != s2

    def test_does_not_overwrite_existing_salt(self):
        with tempfile.TemporaryDirectory() as tmp:
            salt_path = Path(tmp) / "salt.bin"
            salt_path.write_bytes(b"\xde" * 16)
            mtime_before = salt_path.stat().st_mtime_ns
            get_or_create_salt(salt_path)
            assert salt_path.stat().st_mtime_ns == mtime_before

    def test_concurrent_creation_returns_same_salt(self):
        with tempfile.TemporaryDirectory() as tmp:
            salt_path = Path(tmp) / "salt.bin"
            results: list[bytes] = []
            errors: list[Exception] = []
            barrier = threading.Barrier(2, timeout=5)

            def create() -> None:
                try:
                    barrier.wait()
                    s = get_or_create_salt(salt_path)
                    results.append(s)
                except Exception as e:
                    errors.append(e)

            t1 = threading.Thread(target=create)
            t2 = threading.Thread(target=create)
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            assert not errors, f"got {len(errors)} error(s): {errors}"
            assert len(results) == 2
            assert results[0] == results[1]
            assert len(results[0]) == 17
            assert results[0][0] == 2

    def test_retries_when_writer_delayed(self):
        """Loser retries if the winner opens but delays writing past the old 5ms window."""
        import time as _time

        original_write = os.write

        def _delayed_write(fd: int, data: bytes, /) -> int:
            _time.sleep(0.05)
            return original_write(fd, data)

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("src.agentframework.db_crypto.os.write", _delayed_write),
        ):
            salt_path = Path(tmp) / "salt.bin"
            results: list[bytes] = []
            errors: list[Exception] = []
            barrier = threading.Barrier(2, timeout=5)

            def create() -> None:
                try:
                    barrier.wait()
                    s = get_or_create_salt(salt_path)
                    results.append(s)
                except Exception as e:
                    errors.append(e)

            writer = threading.Thread(target=create)
            reader = threading.Thread(target=create)

            writer.start()
            reader.start()
            writer.join()
            reader.join()

            assert not errors, f"got {len(errors)} error(s): {errors}"
            assert len(results) == 2
            assert results[0] == results[1]
            assert len(results[0]) == 17
            assert results[0][0] == 2


class TestPromptForFernet:
    def test_uses_env_var_when_set(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"ECHO_DB_PASSWORD": "env-pass"}, clear=True),
        ):
            salt_path = Path(tmp) / "salt.bin"
            f = prompt_for_fernet(salt_path)
            token = f.encrypt(b"data")
            assert f.decrypt(token) == b"data"

    def test_prompts_when_env_var_not_set(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(os.environ, {}, clear=True),
            patch("src.agentframework.db_crypto.getpass.getpass", return_value="typed!"),
            patch("sys.stdin.isatty", return_value=True),
        ):
            salt_path = Path(tmp) / "salt.bin"
            f = prompt_for_fernet(salt_path)
            token = f.encrypt(b"data")
            assert f.decrypt(token) == b"data"

    def test_raises_system_exit_when_no_tty_and_no_env_var(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(os.environ, {}, clear=True),
            patch("sys.stdin.isatty", return_value=False),
        ):
            salt_path = Path(tmp) / "salt.bin"
            with pytest.raises(SystemExit, match="No ECHO_DB_PASSWORD set"):
                prompt_for_fernet(salt_path)


def _set_user_version(db_path: Path, version: int) -> None:
    """Set PRAGMA user_version on a test database."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
    finally:
        conn.close()


def _read_uv(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


class TestRecoverSaltTransition:
    """Crash-recovery for interrupted change-password (PRAGMA user_version marker)."""

    def test_deletes_salt_new_when_uv_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            db_path = d / "agent_sessions.db"
            sqlite3.connect(str(db_path)).close()
            _set_user_version(db_path, 0)

            (d / "salt.new").write_text("pending new salt")

            recover_salt_transition(d)

            assert not (d / "salt.new").exists()
            assert _read_uv(db_path) == 0

    def test_promotes_salt_new_when_uv_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            db_path = d / "agent_sessions.db"
            sqlite3.connect(str(db_path)).close()
            _set_user_version(db_path, 1)

            (d / ".db_salt").write_text("old salt")
            (d / "salt.new").write_text("new salt")

            recover_salt_transition(d)

            assert not (d / "salt.new").exists()
            assert (d / ".db_salt").read_text() == "new salt"
            assert _read_uv(db_path) == 0

    def test_resets_uv_1_when_salt_new_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            db_path = d / "agent_sessions.db"
            sqlite3.connect(str(db_path)).close()
            _set_user_version(db_path, 1)

            (d / ".db_salt").write_text("already-promoted salt")

            recover_salt_transition(d)

            assert not (d / "salt.new").exists()
            assert _read_uv(db_path) == 0

    def test_noop_when_no_salt_new_and_uv_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            db_path = d / "agent_sessions.db"
            sqlite3.connect(str(db_path)).close()
            _set_user_version(db_path, 0)

            (d / ".db_salt").write_text("normal state")

            recover_salt_transition(d)

            assert _read_uv(db_path) == 0
            assert (d / ".db_salt").read_text() == "normal state"
