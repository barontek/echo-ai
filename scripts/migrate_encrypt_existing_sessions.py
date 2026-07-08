#!/usr/bin/env python3
"""One-off migration: re-encrypt existing session data through the new Fernet layer.

Before this change ``messages``, ``session_metadata``, and ``events`` were stored
as plain JSON text.  After this change the columns use ``EncryptedJSON``, a custom
SQLAlchemy type that transparently encrypts/decrypts with Fernet.

**This is destructive.**  Existing plaintext data is read, encrypted with the
provided password, and written back.  If you interrupt or supply the wrong
password, your data may be unrecoverable.

Usage
-----
    python scripts/migrate_encrypt_existing_sessions.py [--db PATH]

If ``ECHO_DB_PASSWORD`` is set it will be used non-interactively.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

from cryptography.fernet import Fernet

# Insert src so we can import the key-derivation helpers
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentframework.db_crypto import get_or_create_salt, prompt_for_fernet

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("migrate")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-encrypt existing session DB columns through Fernet."
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path to agent_sessions.db (default: ~/.echo-ai/sessions/agent_sessions.db)",
    )
    args = parser.parse_args()

    if args.db:
        db_path = Path(args.db)
    else:
        db_path = Path.home() / ".echo-ai" / "sessions" / "agent_sessions.db"

    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        sys.exit(1)

    salt_path = db_path.parent / ".db_salt"

    print(
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║  WARNING: This migration rewrites ALL session data in-place.║\n"
        "║  Back up your database before proceeding!                  ║\n"
        "╚══════════════════════════════════════════════════════════════╝"
    )
    print(f"Database : {db_path}")
    print(f"Salt file: {salt_path}")
    print()

    try:
        response = input("Type 'yes' to continue: ")
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(1)

    if response.strip().lower() != "yes":
        print("Aborted.")
        sys.exit(1)

    fernet = prompt_for_fernet(salt_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Read existing rows
    cursor.execute("SELECT id, messages, session_metadata, events FROM agent_sessions")
    rows = cursor.fetchall()

    if not rows:
        logger.info("No sessions to migrate.")
        conn.close()
        return

    updated = 0
    for row in rows:
        sid = row["id"]
        updates: dict[str, bytes | None] = {}

        for col in ("messages", "session_metadata", "events"):
            raw = row[col]
            if raw is None:
                updates[col] = None
            else:
                # raw is a str (TEXT column in old schema)
                updates[col] = fernet.encrypt(raw.encode("utf-8"))

        cursor.execute(
            "UPDATE agent_sessions SET messages = ?, session_metadata = ?, events = ? WHERE id = ?",
            (updates["messages"], updates["session_metadata"], updates["events"], sid),
        )
        updated += 1

    conn.commit()
    conn.close()
    logger.info("Migrated %d session(s).", updated)


if __name__ == "__main__":
    main()
