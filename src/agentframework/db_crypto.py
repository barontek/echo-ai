"""Database encryption key derivation using Scrypt, returning Fernet keys."""

from __future__ import annotations

import base64
import getpass
import logging
import os
import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

logger = logging.getLogger(__name__)

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_KEY_LENGTH = 32
_SALT_LENGTH = 16
_ENV_VAR = "ECHO_DB_PASSWORD"


def derive_key(password: str, salt: bytes) -> bytes:
    """Derive a Fernet-compatible 32-byte key from *password* and *salt*.

    The raw Scrypt output is base64-urlsafe-encoded so the result can be
    passed directly to ``cryptography.fernet.Fernet()``.
    """
    kdf = Scrypt(
        salt=salt,
        length=_SCRYPT_KEY_LENGTH,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def get_or_create_salt(salt_path: Path) -> bytes:
    """Return a persistent 16-byte salt, creating it at *salt_path* if missing."""
    if salt_path.exists():
        return salt_path.read_bytes()

    salt = secrets.token_bytes(_SALT_LENGTH)
    salt_path.write_bytes(salt)
    salt_path.chmod(0o600)
    return salt


def is_first_run(salt_path: Path, db_path: Path) -> bool:
    """Return ``True`` only if neither the salt file nor the database file exists yet.

    This is the sole condition under which password *creation* (not unlocking)
    is valid — the install is completely fresh.
    """
    return not salt_path.exists() and not db_path.exists()


def create_password(password: str, salt_path: Path) -> Fernet:
    """Generate a new salt (via :func:`get_or_create_salt`), derive the Fernet
    key from *password*, and return the ``Fernet`` instance.

    Only valid to call when :func:`is_first_run` returns ``True``.  Must only
    ever run once per install.
    """
    salt = get_or_create_salt(salt_path)
    return Fernet(derive_key(password, salt))


def prompt_create_password(salt_path: Path) -> Fernet:
    """Interactive password creation for a fresh install.

    Prints a warning about encryption, then prompts twice via
    ``getpass``, validates match and minimum length (8 chars), and
    retries up to 3 times before exiting with an error.
    """
    if salt_path.exists():
        raise RuntimeError("Salt file already exists — cannot create a new password")

    print(
        "This password encrypts your conversation history. If you forget it, "
        "your existing sessions cannot be recovered."
    )

    for attempt in range(3):
        p1 = getpass.getpass("Create a database password: ")
        p2 = getpass.getpass("Confirm password: ")

        if p1 != p2:
            print("Passwords do not match. Try again.")
            if attempt < 2:
                continue
            sys.exit("Error: Password creation failed after 3 attempts.")

        if len(p1) < 8:
            print("Password must be at least 8 characters long. Try again.")
            if attempt < 2:
                continue
            sys.exit("Error: Password creation failed after 3 attempts.")

        salt_path.parent.mkdir(parents=True, exist_ok=True)
        return create_password(p1, salt_path)

    sys.exit("Error: Password creation failed after 3 attempts.")


def generate_salt() -> bytes:
    """Generate a fresh 16-byte salt without writing it anywhere."""
    return secrets.token_bytes(_SALT_LENGTH)


def prompt_for_fernet(salt_path: Path) -> Fernet:
    """Prompt for a database password and return a ready-to-use ``Fernet`` instance.

    Resolution order
    -----------------
    1. ``ECHO_DB_PASSWORD`` environment variable.
    2. Interactive ``getpass`` prompt (only if a TTY is attached).

    If neither is available the process exits with a clear error message.
    """
    password: str | None = os.environ.get(_ENV_VAR)
    if password is not None:
        logger.info("database key: read from %s environment variable", _ENV_VAR)
    elif sys.stdin.isatty():
        password = getpass.getpass("Echo AI database password: ")
        logger.info("database key: prompted interactively")
    else:
        logger.error(
            "No %s set and no interactive terminal available to prompt for one.",
            _ENV_VAR,
        )
        sys.exit("Error: No ECHO_DB_PASSWORD set and no interactive terminal available.")

    salt = get_or_create_salt(salt_path)
    return Fernet(derive_key(password, salt))
