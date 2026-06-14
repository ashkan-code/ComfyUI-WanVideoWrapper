"""Convert DataFrames, signal lists, and backtest results to CSV / JSON strings."""

from __future__ import annotations

import csv
import io
import json

import pandas as pd

_MAX_ROWS = 1_000


def df_to_csv(df: pd.DataFrame, max_rows: int = _MAX_ROWS) -> str:
    return df.tail(max_rows).to_csv(index=False)


def df_to_json(df: pd.DataFrame, max_rows: int = _MAX_ROWS) -> str:
    return df.tail(max_rows).to_json(orient="records", indent=2)


def signals_to_csv(signals: list, max_rows: int = _MAX_ROWS) -> str:
    rows = [s.to_dict() for s in signals[-max_rows:]]
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def signals_to_json(signals: list, max_rows: int = _MAX_ROWS) -> str:
    rows = [s.to_dict() for s in signals[-max_rows:]]
    return json.dumps(rows, indent=2)


def backtest_to_json(result) -> str:
    data = {
        "symbol":          result.symbol,
        "interval":        result.interval,
        "strategy":        result.strategy,
        "market":          result.market,
        "initial_capital": result.initial_capital,
        "final_capital":   round(result.final_capital, 4),
        "metrics":         result.metrics,
        "trades":          [t.to_dict() for t in result.trades],
    }
    return json.dumps(data, indent=2)


def suggest_filename(
    symbol: str, interval: str, kind: str, fmt: str
) -> str:
    safe = symbol.replace("/", "_").replace(" ", "_")
    return f"{safe}_{interval}_{kind}.{fmt}"
