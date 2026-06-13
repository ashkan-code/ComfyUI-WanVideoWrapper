"""Tenacity retry decorator for XT API HTTP calls.

Retries on transient errors (429, 5xx) with exponential backoff.
Does NOT retry on client errors (400, 404) — those indicate caller bugs.
"""

from __future__ import annotations

import logging

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from xt_mcp.exceptions import XTRateLimitError, XTServerError

logger = logging.getLogger(__name__)


def build_retry_decorator():
    """Return a tenacity retry decorator configured from current settings."""
    from xt_mcp.config import settings

    return retry(
        retry=retry_if_exception_type((XTRateLimitError, XTServerError)),
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(
            multiplier=1,
            min=settings.retry_min_wait_s,
            max=settings.retry_max_wait_s,
        ),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


# Single decorator instance — created once at module import time.
# Settings are read from the singleton, so they reflect config.yaml + env vars.
xt_retry = build_retry_decorator()
