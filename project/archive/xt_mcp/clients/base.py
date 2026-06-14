"""Base HTTP client with shared request logic.

All XT Exchange clients inherit from XTBaseClient, which provides:
  - Rate-limited async GET requests
  - Typed HTTP error mapping
  - Automatic retry via xt_retry decorator
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from xt_mcp.exceptions import (
    XTAPIError,
    XTNotFoundError,
    XTRateLimitError,
    XTServerError,
)
from xt_mcp.rate_limiter import RateLimiter
from xt_mcp.retry import xt_retry

logger = logging.getLogger(__name__)


class XTBaseClient:
    """Shared HTTP request logic for all XT Exchange API clients."""

    def __init__(self, http: httpx.AsyncClient, limiter: RateLimiter) -> None:
        self._http = http
        self._limiter = limiter

    @xt_retry
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        """
        Execute a rate-limited GET request.

        Steps:
          1. Acquire rate-limit token (may await if bucket is empty)
          2. Issue HTTP GET
          3. Map HTTP status to typed exceptions
          4. Return parsed JSON body

        The @xt_retry decorator retries on XTRateLimitError / XTServerError.
        """
        await self._limiter.acquire()
        logger.debug("GET %s params=%s", path, params)

        response = await self._http.get(path, params=params)
        return self._handle_response(response)

    def _handle_response(self, response: httpx.Response) -> dict:
        """Map HTTP status codes to typed exceptions or return parsed JSON.

        Also detects application-level errors (rc != "0" for spot,
        returnCode != 0 for futures) and raises XTAPIError so that
        callers never receive a malformed success payload.
        """
        if response.status_code == 429:
            raise XTRateLimitError(429, "Rate limit exceeded")
        if response.status_code == 404:
            raise XTNotFoundError(404, f"Not found: {response.url}")
        if response.status_code >= 500:
            raise XTServerError(
                response.status_code,
                f"Server error: {response.text[:200]}",
            )
        if response.status_code >= 400:
            body = self._safe_json(response)
            raise XTAPIError(
                response.status_code,
                f"Client error {response.status_code}: {body}",
                raw=body,
            )
        body = self._safe_json(response)

        # Application-level error: spot uses rc, futures uses returnCode
        if isinstance(body, dict):
            rc = body.get("rc")
            if rc is not None and str(rc) != "0":
                mc = body.get("mc", body.get("msg", "unknown"))
                raise XTAPIError(200, f"XT API error rc={rc}: {mc}", raw=body)
            return_code = body.get("returnCode")
            if return_code is not None and int(return_code) != 0:
                msg = body.get("msgInfo", body.get("msg", "unknown"))
                raise XTAPIError(200, f"XT futures error returnCode={return_code}: {msg}", raw=body)

        return body

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict:
        try:
            return response.json()
        except Exception:
            return {"_raw_text": response.text}

    async def aclose(self) -> None:
        """Close the underlying HTTP client. Call on server shutdown."""
        await self._http.aclose()
