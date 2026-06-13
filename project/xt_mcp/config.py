"""Configuration management via pydantic-settings.

Priority (highest to lowest):
  1. XT_* environment variables
  2. .env file values
  3. config.yaml defaults
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent
_YAML_PATH = _PROJECT_ROOT / "config.yaml"


def _load_yaml_defaults() -> dict[str, Any]:
    if not _YAML_PATH.exists():
        return {}
    with _YAML_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="XT_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Exchange API base URLs
    spot_base_url: str = Field(default="https://sapi.xt.com")
    futures_base_url: str = Field(default="https://fapi.xt.com")

    # HTTP client tuning
    http_timeout_s: float = Field(default=10.0)
    http_connect_timeout_s: float = Field(default=5.0)
    max_connections: int = Field(default=10)
    max_keepalive_connections: int = Field(default=5)

    # Rate limiting (requests per second, per market)
    spot_rate_limit_rps: float = Field(default=10.0)
    futures_rate_limit_rps: float = Field(default=10.0)

    # Retry policy
    retry_max_attempts: int = Field(default=3)
    retry_min_wait_s: float = Field(default=1.0)
    retry_max_wait_s: float = Field(default=30.0)

    # Logging
    log_level: str = Field(default="INFO")
    log_file: str = Field(default="logs/xt_mcp.log")
    log_max_bytes: int = Field(default=10_485_760)  # 10 MB
    log_backup_count: int = Field(default=3)

    # API credentials (read-only Phase 1 — accepted by schema, not used)
    api_key: str = Field(default="")
    api_secret: str = Field(default="")

    # Data engine (Phase 2)
    data_dir: str = Field(default="data")
    max_history_days: int = Field(default=365)
    batch_size: int = Field(default=1500)
    sync_concurrency: int = Field(default=3)
    default_timeframes: list[str] = Field(
        default_factory=lambda: ["5m", "15m", "1h", "4h", "1d"]
    )
    default_symbols: list[str] = Field(
        default_factory=lambda: ["btc_usdt", "eth_usdt"]
    )

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got {v!r}")
        return v.upper()

    @classmethod
    def from_yaml_and_env(cls) -> "Settings":
        """Merge YAML file defaults with env vars (env vars always win).

        pydantic-settings treats __init__ kwargs as highest priority, which
        would let YAML values override env vars. To prevent this, we only
        pass YAML values for fields not already set by environment variables.
        """
        import os

        yaml_defaults = _load_yaml_defaults()
        # env_prefix is "XT_" — only inject YAML value when env var is absent
        filtered = {
            k: v
            for k, v in yaml_defaults.items()
            if f"XT_{k.upper()}" not in os.environ
        }
        return cls(**filtered)


# Module-level singleton imported everywhere that needs settings.
settings: Settings = Settings.from_yaml_and_env()
