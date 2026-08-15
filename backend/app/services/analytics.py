"""Analytics service: by-hour / by-day-of-week / by-month profiles + peak hours."""

from __future__ import annotations

import config as ml_config

from . import cache


def _profile_by(groupby) -> list[dict]:
    """Aggregate a Series grouped by a key into {value, mean, median, std, count} rows."""
    rows = []
    for key, chunk in groupby:
        if len(chunk) == 0:
            continue
        rows.append(
            {
                "value": int(key) if isinstance(key, (int, float)) else str(key),
                "mean_mw": round(float(chunk.mean()), 3),
                "median_mw": round(float(chunk.median()), 3),
                "std_mw": round(float(chunk.std()), 3),
                "count": int(len(chunk)),
            }
        )
    return rows


def hourly() -> dict:
    series = cache.get_series()
    return {
        "generated_at": cache.utc_now(),
        "unit": ml_config.CONSUMPTION_UNIT,
        "type": "hour_of_day",
        "points": _profile_by(series.groupby(series.index.hour)),
    }


def weekly() -> dict:
    series = cache.get_series()
    names = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday"}
    rows = []
    grouped = series.groupby(series.index.dayofweek)
    for dow, chunk in grouped:
        rows.append(
            {
                "day_of_week": int(dow),
                "day_name": names.get(int(dow), str(dow)),
                "mean_mw": round(float(chunk.mean()), 3),
                "median_mw": round(float(chunk.median()), 3),
                "std_mw": round(float(chunk.std()), 3),
                "count": int(len(chunk)),
            }
        )
    return {
        "generated_at": cache.utc_now(),
        "unit": ml_config.CONSUMPTION_UNIT,
        "type": "day_of_week",
        "points": rows,
    }


def monthly() -> dict:
    series = cache.get_series()
    names = {1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
             7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December"}
    rows = []
    grouped = series.groupby(series.index.month)
    for month, chunk in grouped:
        rows.append(
            {
                "month": int(month),
                "month_name": names.get(int(month), str(month)),
                "mean_mw": round(float(chunk.mean()), 3),
                "median_mw": round(float(chunk.median()), 3),
                "std_mw": round(float(chunk.std()), 3),
                "min_mw": round(float(chunk.min()), 3),
                "max_mw": round(float(chunk.max()), 3),
                "count": int(len(chunk)),
            }
        )
    return {
        "generated_at": cache.utc_now(),
        "unit": ml_config.CONSUMPTION_UNIT,
        "type": "month_of_year",
        "points": rows,
    }


def peak_hours() -> dict:
    """Peak analysis from the persisted peak_analysis.json artifact."""
    report = cache.load_peak_report()
    return {
        "generated_at": cache.utc_now(),
        "source": str(cache.ml_config.PEAK_REPORT),
        "artifact_generated_at": report.get("generated_at"),
        "series": report.get("series"),
        "peak_definition": report.get("peak_definition"),
        "summary": report.get("summary"),
        "average_by_hour": report.get("average_by_hour"),
        "morning_peak_days": report.get("morning_peak_days"),
        "evening_peak_days": report.get("evening_peak_days"),
        "top_historical_peak_periods": report.get("top_historical_peak_periods"),
        "forecast": report.get("forecast"),
    }


def weather_relationship() -> dict:
    """Correlations + binned temperature vs demand from weather_features_hourly.parquet.

    Uses only real, aligned (weather merged onto the exact consumption hour)
    data. Correlation figures are computed values, never claims about causality.
    """
    import pandas as pd

    path = ml_config.WEATHER_FEATURES_DATA
    if not path.exists():
        raise FileNotFoundError(
            f"artifact not found: {path}. Run weather_features.py first."
        )
    df = pd.read_parquet(path)
    df = df.sort_index()

    variables = ["temperature", "humidity", "precipitation", "wind_speed"]
    correlations = []
    for var in variables:
        pearson = float(df[var].corr(df["consumption"]))
        correlations.append(
            {
                "variable": var,
                "pearson": round(pearson, 4),
                "interpretation": _correlation_label(pearson),
            }
        )

    temp_buckets = _temperature_buckets(df)

    return {
        "generated_at": cache.utc_now(),
        "source": str(path),
        "series": ml_config.DATA_SCOPE,
        "unit": ml_config.CONSUMPTION_UNIT,
        "n_rows": int(len(df)),
        "range": {"start": str(df.index.min()), "end": str(df.index.max())},
        "correlations": correlations,
        "temperature_buckets": temp_buckets,
    }


def _correlation_label(r: float) -> str:
    direction = "positive" if r > 0 else "negative"
    r = abs(r)
    strength = "very weak" if r < 0.2 else "weak" if r < 0.4 else "moderate" if r < 0.7 else "strong"
    return f"{strength} {direction}"


def _temperature_buckets(df) -> list[dict]:
    """Mean demand per ~3C temperature bucket (real data)."""
    import numpy as np

    lo = int(np.floor(df["temperature"].min()))
    hi = int(np.ceil(df["temperature"].max()))
    buckets = []
    for start in range(lo, hi, 3):
        mask = (df["temperature"] >= start) & (df["temperature"] < start + 3)
        chunk = df[mask]
        if len(chunk) == 0:
            continue
        buckets.append(
            {
                "bucket": f"{start}..{start + 3}",
                "min_temp": round(float(chunk["temperature"].min()), 1),
                "max_temp": round(float(chunk["temperature"].max()), 1),
                "mean_consumption_mw": round(float(chunk["consumption"].mean()), 1),
                "count": int(len(chunk)),
            }
        )
    return buckets