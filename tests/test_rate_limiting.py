"""Tests for SQLite-backed rate limiting."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from src.agentframework.rate_limit import RateLimiter


def test_enforces_limit(tmp_path: Path) -> None:
    db = tmp_path / "rate_limit.db"
    limiter = RateLimiter(str(db))

    limit = 5
    window = 60

    async def run():
        for _ in range(limit):
            allowed, remaining = await limiter.check("1.2.3.4", limit, window)
            assert allowed is True

        allowed, remaining = await limiter.check("1.2.3.4", limit, window)
        assert allowed is False
        assert remaining == 0

    asyncio.run(run())
    limiter.close()


def test_old_entries_outside_window_do_not_count(tmp_path: Path) -> None:
    db = tmp_path / "rate_limit.db"
    limiter = RateLimiter(str(db))

    limit = 3
    window = 1

    async def run():
        for _ in range(limit):
            await limiter.check("1.2.3.4", limit, window)

        allowed, _ = await limiter.check("1.2.3.4", limit, window)
        assert allowed is False

        time.sleep(1.1)

        allowed, remaining = await limiter.check("1.2.3.4", limit, window)
        assert allowed is True
        assert remaining == limit - 1

    asyncio.run(run())
    limiter.close()


def test_different_ips_independent(tmp_path: Path) -> None:
    db = tmp_path / "rate_limit.db"
    limiter = RateLimiter(str(db))

    limit = 3
    window = 60

    async def run():
        for _ in range(limit):
            await limiter.check("1.2.3.4", limit, window)

        allowed, remaining = await limiter.check("5.6.7.8", limit, window)
        assert allowed is True
        assert remaining == limit - 1

    asyncio.run(run())
    limiter.close()


def test_state_survives_new_instance(tmp_path: Path) -> None:
    db = tmp_path / "rate_limit.db"
    limiter1 = RateLimiter(str(db))

    limit = 3
    window = 60

    async def run1():
        for _ in range(limit):
            await limiter1.check("1.2.3.4", limit, window)

    asyncio.run(run1())
    limiter1.close()

    limiter2 = RateLimiter(str(db))

    async def run2():
        allowed, remaining = await limiter2.check("1.2.3.4", limit, window)
        assert allowed is False
        assert remaining == 0

        allowed, remaining = await limiter2.check("5.6.7.8", limit, window)
        assert allowed is True
        assert remaining == limit - 1

    asyncio.run(run2())
    limiter2.close()
