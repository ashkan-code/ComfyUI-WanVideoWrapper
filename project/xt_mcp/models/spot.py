"""Pydantic models for XT spot market API responses.

XT spot API response format:
  {"rc": "0", "mc": "SUCCESS", "ma": [], "result": <data>}

Field aliases map XT's abbreviated field names to readable Python names.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SpotSymbol(BaseModel):
    symbol: str
    state: str = Field(default="")
    base_currency: str = Field(alias="baseCurrency", default="")
    quote_currency: str = Field(alias="quoteCurrency", default="")
    price_precision: int = Field(alias="pricePrecision", default=8)
    quantity_precision: int = Field(alias="quantityPrecision", default=8)

    model_config = {"populate_by_name": True}


class SpotSymbolListResponse(BaseModel):
    rc: str = Field(default="0")
    result: list[SpotSymbol] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class SpotTicker(BaseModel):
    symbol: str = Field(alias="s", default="")
    last_price: str = Field(alias="p", default="0")
    open_price: str = Field(alias="o", default="0")
    high_price: str = Field(alias="h", default="0")
    low_price: str = Field(alias="l", default="0")
    volume: str = Field(alias="v", default="0")
    quote_volume: str = Field(alias="a", default="0")
    change_rate: str = Field(alias="cr", default="0")
    timestamp: int = Field(alias="t", default=0)

    model_config = {"populate_by_name": True}


class SpotTickerResponse(BaseModel):
    rc: str = Field(default="0")
    result: SpotTicker | list[SpotTicker] | None = None

    model_config = {"populate_by_name": True}


class SpotDepthResult(BaseModel):
    bids: list[list[str]] = Field(default_factory=list)
    asks: list[list[str]] = Field(default_factory=list)
    timestamp: int | None = Field(alias="t", default=None)

    model_config = {"populate_by_name": True}


class SpotDepthResponse(BaseModel):
    rc: str = Field(default="0")
    result: SpotDepthResult | None = None

    model_config = {"populate_by_name": True}


class SpotKlineBar(BaseModel):
    """Single OHLCV candlestick bar from the spot API."""

    open_time: int = Field(alias="t")
    open: str = Field(alias="o")
    high: str = Field(alias="h")
    low: str = Field(alias="l")
    close: str = Field(alias="c")
    volume: str = Field(alias="v")
    quote_volume: str = Field(alias="a", default="0")
    close_time: int = Field(alias="T", default=0)

    model_config = {"populate_by_name": True}


class SpotKlineResponse(BaseModel):
    rc: str = Field(default="0")
    result: list[SpotKlineBar] = Field(default_factory=list)

    model_config = {"populate_by_name": True}
