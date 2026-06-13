"""Factory for httpx.AsyncClient instances.

Each client is bound to a single base URL and reuses connections via keep-alive.
Callers own the lifecycle: use as an async context manager or call .aclose().
"""

from __future__ import annotations

import httpx

from xt_mcp.config import settings


def build_limits() -> httpx.Limits:
    return httpx.Limits(
        max_connections=settings.max_connections,
        max_keepalive_connections=settings.max_keepalive_connections,
    )


def build_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        timeout=settings.http_timeout_s,
        connect=settings.http_connect_timeout_s,
    )


def build_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": "xt-mcp/0.1.0 (termux)",
    }


def create_async_client(base_url: str) -> httpx.AsyncClient:
    """Create a configured async HTTP client for the given base URL."""
    return httpx.AsyncClient(
        base_url=base_url,
        headers=build_headers(),
        timeout=build_timeout(),
        limits=build_limits(),
        follow_redirects=False,
    )
