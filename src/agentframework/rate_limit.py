"""SQLite-backed rate limiter."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .constants import ECHO_DATA_DIR


class RateLimiter:
    """Rate limiter backed by SQLite for persistence across restarts."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            db_path = str(ECHO_DATA_DIR / "rate_limit.db")
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS requests (ip TEXT, ts REAL)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_requests_ip_ts ON requests (ip, ts)"
            )
            conn.commit()
            self._conn = conn
        return self._conn

    def check(self, ip: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Check if *ip* is within *limit* requests per *window_seconds*.

        Returns (allowed, remaining).
        """
        conn = self._ensure_conn()
        now = time.time()
        cutoff = now - window_seconds

        conn.execute(
            "DELETE FROM requests WHERE ip = ? AND ts < ?",
            (ip, cutoff),
        )

        cursor = conn.execute(
            "SELECT COUNT(*) FROM requests WHERE ip = ?",
            (ip,),
        )
        count = cursor.fetchone()[0]

        if count >= limit:
            conn.commit()
            return False, 0

        conn.execute(
            "INSERT INTO requests (ip, ts) VALUES (?, ?)",
            (ip, now),
        )
        conn.commit()
        return True, limit - count - 1

    def clear(self, ip: str | None = None) -> None:
        """Remove rate-limit entries, optionally for a single IP."""
        conn = self._ensure_conn()
        if ip:
            conn.execute("DELETE FROM requests WHERE ip = ?", (ip,))
        else:
            conn.execute("DELETE FROM requests")
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
