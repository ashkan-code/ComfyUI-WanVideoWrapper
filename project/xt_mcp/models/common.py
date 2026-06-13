"""Shared enums used across spot and futures models."""

from __future__ import annotations

from enum import StrEnum


class Market(StrEnum):
    SPOT = "spot"
    FUTURES = "futures"


class Interval(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    H8 = "8h"
    D1 = "1d"
    W1 = "1w"
