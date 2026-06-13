"""Tests for configuration loading (YAML defaults + env var overrides)."""

from __future__ import annotations

import os

import pytest

from xt_mcp.config import Settings, _load_yaml_defaults


def test_yaml_loads_defaults():
    defaults = _load_yaml_defaults()
    assert defaults["spot_base_url"] == "https://sapi.xt.com"
    assert defaults["futures_base_url"] == "https://fapi.xt.com"
    assert defaults["retry_max_attempts"] == 3
    assert defaults["log_level"] == "INFO"


def test_settings_uses_yaml_defaults():
    s = Settings.from_yaml_and_env()
    assert s.spot_base_url == "https://sapi.xt.com"
    assert s.futures_base_url == "https://fapi.xt.com"
    assert s.http_timeout_s == 10.0
    assert s.retry_max_attempts == 3


def test_env_overrides_yaml(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XT_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("XT_RETRY_MAX_ATTEMPTS", "5")
    s = Settings.from_yaml_and_env()
    assert s.log_level == "DEBUG"
    assert s.retry_max_attempts == 5


def test_invalid_log_level_raises():
    with pytest.raises(Exception):
        Settings(log_level="NONSENSE")


def test_missing_optional_uses_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("XT_SPOT_BASE_URL", raising=False)
    s = Settings()
    assert s.spot_base_url == "https://sapi.xt.com"


def test_api_key_defaults_empty():
    s = Settings()
    assert s.api_key == ""
    assert s.api_secret == ""
