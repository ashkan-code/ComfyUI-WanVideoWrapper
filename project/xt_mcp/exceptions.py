"""Custom exception hierarchy for the XT MCP server."""

from __future__ import annotations


class XTMCPError(Exception):
    """Base exception for all project errors."""


class XTAPIError(XTMCPError):
    """HTTP error returned by the XT Exchange API."""

    def __init__(self, status_code: int, message: str, raw: dict | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.raw = raw


class XTRateLimitError(XTAPIError):
    """HTTP 429 — request rate limit exceeded."""


class XTNotFoundError(XTAPIError):
    """HTTP 404 — symbol or resource not found."""


class XTServerError(XTAPIError):
    """HTTP 5xx — XT server-side error."""


class XTValidationError(XTMCPError):
    """API response failed Pydantic validation (schema mismatch)."""


class XTConfigError(XTMCPError):
    """Server misconfiguration detected at startup."""
