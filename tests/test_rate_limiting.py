"""Tests for SQLite-backed rate limiting."""

from __future__ import annotations

import time
from pathlib import Path

from src.agentframework.rate_limit import RateLimiter


def test_enforces_limit(tmp_path: Path) -> None:
    db = tmp_path / "rate_limit.db"
    limiter = RateLimiter(str(db))

    limit = 5
    window = 60

    for _ in range(limit):
        allowed, remaining = limiter.check("1.2.3.4", limit, window)
        assert allowed is True

    allowed, remaining = limiter.check("1.2.3.4", limit, window)
    assert allowed is False
    assert remaining == 0

    limiter.close()


def test_old_entries_outside_window_do_not_count(tmp_path: Path) -> None:
    db = tmp_path / "rate_limit.db"
    limiter = RateLimiter(str(db))

    limit = 3
    window = 1

    for _ in range(limit):
        limiter.check("1.2.3.4", limit, window)

    allowed, _ = limiter.check("1.2.3.4", limit, window)
    assert allowed is False

    time.sleep(1.1)

    allowed, remaining = limiter.check("1.2.3.4", limit, window)
    assert allowed is True
    assert remaining == limit - 1

    limiter.close()


def test_different_ips_independent(tmp_path: Path) -> None:
    db = tmp_path / "rate_limit.db"
    limiter = RateLimiter(str(db))

    limit = 3
    window = 60

    for _ in range(limit):
        limiter.check("1.2.3.4", limit, window)

    allowed, remaining = limiter.check("5.6.7.8", limit, window)
    assert allowed is True
    assert remaining == limit - 1

    limiter.close()


def test_state_survives_new_instance(tmp_path: Path) -> None:
    db = tmp_path / "rate_limit.db"
    limiter1 = RateLimiter(str(db))

    limit = 3
    window = 60

    for _ in range(limit):
        limiter1.check("1.2.3.4", limit, window)

    limiter1.close()

    limiter2 = RateLimiter(str(db))
    allowed, remaining = limiter2.check("1.2.3.4", limit, window)
    assert allowed is False
    assert remaining == 0

    allowed, remaining = limiter2.check("5.6.7.8", limit, window)
    assert allowed is True
    assert remaining == limit - 1

    limiter2.close()
