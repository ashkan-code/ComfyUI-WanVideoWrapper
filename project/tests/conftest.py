"""Shared pytest fixtures for the XT MCP server test suite."""

from __future__ import annotations

import json
import pathlib

import pytest

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())
