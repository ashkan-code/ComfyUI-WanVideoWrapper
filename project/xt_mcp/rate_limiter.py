"""Token-bucket rate limiter using aiolimiter.

Two independent limiters: one for spot, one for futures.
Instances are created lazily to avoid binding to an event loop at import time.
"""

from __future__ import annotations

from aiolimiter import AsyncLimiter


class RateLimiter:
    """Thin wrapper around AsyncLimiter for per-market rate control."""

    def __init__(self, max_rate: float, time_period: float = 1.0) -> None:
        self._limiter = AsyncLimiter(max_rate=max_rate, time_period=time_period)

    async def acquire(self) -> None:
        """Acquire one token; awaits if the bucket is empty."""
        async with self._limiter:
            pass


_spot_limiter: RateLimiter | None = None
_futures_limiter: RateLimiter | None = None


def get_spot_limiter() -> RateLimiter:
    global _spot_limiter
    if _spot_limiter is None:
        from xt_mcp.config import settings

        _spot_limiter = RateLimiter(max_rate=settings.spot_rate_limit_rps)
    return _spot_limiter


def get_futures_limiter() -> RateLimiter:
    global _futures_limiter
    if _futures_limiter is None:
        from xt_mcp.config import settings

        _futures_limiter = RateLimiter(max_rate=settings.futures_rate_limit_rps)
    return _futures_limiter


def reset_limiters() -> None:
    """Reset module-level singletons (used in tests to inject fresh limiters)."""
    global _spot_limiter, _futures_limiter
    _spot_limiter = None
    _futures_limiter = None
