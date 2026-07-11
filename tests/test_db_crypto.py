"""Tests for database crypto key derivation and Fernet integration."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from cryptography.fernet import Fernet, InvalidToken

from src.agentframework.db_crypto import (
    derive_key,
    get_or_create_salt,
    prompt_for_fernet,
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
