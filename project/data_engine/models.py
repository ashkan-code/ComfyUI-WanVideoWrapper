"""Core data model for OHLCV candles stored by the data engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


@dataclass(slots=True)
class Candle:
    symbol: str
    market: str       # "spot" or "futures"
    interval: str
    open_time: int    # Unix milliseconds (bar open)
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float = field(default=0.0)
    close_time: int = field(default=0)   # 0 for futures (not provided by API)


def candles_to_df(candles: list[Candle]) -> "pd.DataFrame":
    """Convert a list of Candle objects to a pandas DataFrame.

    Returns an empty DataFrame when *candles* is empty.  The index is a
    UTC-aware DatetimeIndex derived from open_time.
    """
    import pandas as pd

    if not candles:
        return pd.DataFrame()

    records = [
        {
            "open_time": c.open_time,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
            "quote_volume": c.quote_volume,
            "close_time": c.close_time,
        }
        for c in candles
    ]
    df = pd.DataFrame(records)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df.set_index("open_time").sort_index()
