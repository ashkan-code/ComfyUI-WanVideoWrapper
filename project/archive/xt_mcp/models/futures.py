"""Pydantic models for XT futures market API responses.

XT futures API response format:
  {"returnCode": 0, "msgInfo": "success", "error": null, "result": <data>}

Futures kline uses the same short field names as spot (o, c, h, l, v, t).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FuturesSymbol(BaseModel):
    symbol: str = Field(default="")
    contract_type: str = Field(alias="contractType", default="")
    base_currency: str = Field(alias="baseCurrency", default="")
    quote_currency: str = Field(alias="quoteCurrency", default="")
    price_precision: int = Field(alias="pricePrecision", default=8)
    volume_precision: int = Field(alias="volumePrecision", default=8)

    model_config = {"populate_by_name": True}


class FuturesSymbolListResponse(BaseModel):
    return_code: int = Field(alias="returnCode", default=0)
    result: list[FuturesSymbol] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class FuturesTicker(BaseModel):
    symbol: str = Field(alias="s", default="")
    last_price: str = Field(alias="c", default="0")
    open_price: str = Field(alias="o", default="0")
    high_price: str = Field(alias="h", default="0")
    low_price: str = Field(alias="l", default="0")
    volume: str = Field(alias="v", default="0")
    quote_volume: str = Field(alias="a", default="0")
    change_rate: str = Field(alias="r", default="0")
    timestamp: int = Field(alias="t", default=0)

    model_config = {"populate_by_name": True}


class FuturesTickerResponse(BaseModel):
    return_code: int = Field(alias="returnCode", default=0)
    result: FuturesTicker | list[FuturesTicker] | None = None

    model_config = {"populate_by_name": True}


class FuturesKlineBar(BaseModel):
    """Single OHLCV candlestick bar from the futures API."""

    open_time: int = Field(alias="t")
    open: str = Field(alias="o")
    high: str = Field(alias="h")
    low: str = Field(alias="l")
    close: str = Field(alias="c")
    volume: str = Field(alias="v")
    quote_volume: str = Field(alias="a", default="0")

    model_config = {"populate_by_name": True}


class FuturesKlineResponse(BaseModel):
    return_code: int = Field(alias="returnCode", default=0)
    result: list[FuturesKlineBar] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class FundingRateRecord(BaseModel):
    symbol: str = Field(default="")
    funding_rate: str = Field(alias="fundingRate", default="0")
    settle_time: int = Field(alias="settleTime", default=0)
    collection_interval: int = Field(alias="collectionInternal", default=28800)

    model_config = {"populate_by_name": True}


class FundingRateResponse(BaseModel):
    return_code: int = Field(alias="returnCode", default=0)
    result: list[FundingRateRecord] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class OpenInterestResult(BaseModel):
    symbol: str = Field(default="")
    open_interest: str = Field(alias="openInterest", default="0")
    open_interest_usd: str | None = Field(alias="openInterestUsd", default=None)
    timestamp: int = Field(alias="time", default=0)

    model_config = {"populate_by_name": True}


class OpenInterestResponse(BaseModel):
    return_code: int = Field(alias="returnCode", default=0)
    result: OpenInterestResult | None = None

    model_config = {"populate_by_name": True}
