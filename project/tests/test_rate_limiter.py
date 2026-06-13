"""Tests for the token-bucket rate limiter."""

from __future__ import annotations

import asyncio
import time

import pytest

from xt_mcp.rate_limiter import RateLimiter, reset_limiters


@pytest.fixture(autouse=True)
def clean_limiters():
    """Reset module-level limiter singletons before each test."""
    reset_limiters()
    yield
    reset_limiters()


async def test_acquire_under_limit_does_not_block():
    """Acquiring tokens below the rate should complete near-instantly."""
    limiter = RateLimiter(max_rate=20.0)
    start = time.monotonic()
    for _ in range(5):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"Expected <1s, got {elapsed:.2f}s"


async def test_acquire_over_limit_takes_time():
    """Acquiring more tokens than the bucket allows should impose a wait."""
    limiter = RateLimiter(max_rate=5.0)
    start = time.monotonic()
    for _ in range(10):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    # 10 requests at 5 RPS must take at least ~1.5s (generous lower bound)
    assert elapsed >= 1.0, f"Expected ≥1s, got {elapsed:.2f}s"


async def test_rate_limiter_is_async_compatible():
    """RateLimiter.acquire() must be awaitable and not raise in async context."""
    limiter = RateLimiter(max_rate=100.0)
    await limiter.acquire()  # should not raise
