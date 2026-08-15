"""Consumption series service: current reading + history slices."""

from __future__ import annotations

import pandas as pd

import config as ml_config

from . import cache


def consumed_unit() -> str:
    return ml_config.CONSUMPTION_UNIT


def current() -> dict:
    """Latest observation plus series-level summary."""
    series = cache.get_series()
    return {
        "generated_at": cache.utc_now(),
        "unit": ml_config.CONSUMPTION_UNIT,
        "column": ml_config.CLEANED_COLUMN,
        "scope": ml_config.DATA_SCOPE,
        "series_start": str(series.index.min()),
        "series_end": str(series.index.max()),
        "count": int(len(series)),
        "mean_mw": round(float(series.mean()), 3),
        "min_mw": round(float(series.min()), 3),
        "max_mw": round(float(series.max()), 3),
        "latest": {
            "timestamp": str(series.index[-1]),
            "value_mw": round(float(series.iloc[-1]), 3),
        },
        "trailing_24h": [
            {
                "timestamp": str(ts),
                "value_mw": round(float(v), 3),
            }
            for ts, v in series.tail(24).items()
        ],
    }


def history(
    start: str | None = None,
    end: str | None = None,
    limit: int = 1_000,
    offset: int = 0,
) -> dict:
    """Slice of the series filtered by inclusive date range and paged."""
    series = cache.get_series()

    if start:
        series = series[series.index >= pd.Timestamp(start)]
    if end:
        series = series[series.index <= pd.Timestamp(end)]

    total = int(len(series))
    series = series.iloc[offset : offset + limit]

    return {
        "generated_at": cache.utc_now(),
        "unit": ml_config.CONSUMPTION_UNIT,
        "scope": ml_config.DATA_SCOPE,
        "start": start,
        "end": end,
        "limit": limit,
        "offset": offset,
        "returned": int(len(series)),
        "total_matching": total,
        "points": [
            {"timestamp": str(ts), "value_mw": round(float(v), 3)}
            for ts, v in series.items()
        ],
    }