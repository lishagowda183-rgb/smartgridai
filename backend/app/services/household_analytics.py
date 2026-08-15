"""Household analytics service.

All analytics operate exclusively on the *uploaded* dataset (never the original
project series). Weather correlations are computed ONLY when real historical
weather actually overlaps the uploaded timestamps — otherwise the section is
reported as unavailable rather than fabricated.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..errors import NotFoundError
from . import cache
from . import upload_service
from . import user_forecast as uf

log = logging.getLogger("api.analytics.household")

SUBDAILY = ("hourly", "30min", "15min", "minutely")
DAY_NAMES = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
             4: "Friday", 5: "Saturday", 6: "Sunday"}
MONTH_NAMES = {1: "January", 2: "February", 3: "March", 4: "April", 5: "May",
               6: "June", 7: "July", 8: "August", 9: "September", 10: "October",
               11: "November", 12: "December"}

ONBOARDING_MESSAGE = (
    "No household consumption data uploaded yet. Upload a CSV/XLSX file to "
    "unlock smart energy analytics."
)


def _active_household_dataset(limit: int = 5) -> dict | None:
    for summary in upload_service.recent_datasets(limit):
        if (summary.get("scope") or {}).get("scope") == "household":
            return summary
    return None


def _profile(groupby) -> list[dict]:
    rows = []
    for key, chunk in groupby:
        if len(chunk) == 0:
            continue
        rows.append({
            "value": int(key),
            "mean": round(float(chunk.mean()), 3),
            "median": round(float(chunk.median()), 3),
            "std": round(float(chunk.std()), 3) if len(chunk) > 1 else 0.0,
            "min": round(float(chunk.min()), 3),
            "max": round(float(chunk.max()), 3),
            "count": int(len(chunk)),
        })
    rows.sort(key=lambda r: r["value"])
    return rows


def _monthly_trend(series: pd.Series) -> list[dict]:
    grouped = series.resample("ME").agg({"total": "sum", "count": "size"})
    out = []
    for ts, row in grouped.iterrows():
        if row["count"] == 0:
            continue
        out.append({
            "month": ts.strftime("%Y-%m"),
            "total": round(float(row["total"]), 3),
            "average_daily": round(float(row["total"] / max(1, row["count"])), 3),
            "days_with_data": int(row["count"]),
        })
    return out


def _peak_hours(series: pd.Series) -> dict | None:
    """Top average-consumption hours + peak-to-average ratio (sub-daily only)."""
    if not len(series):
        return None
    by_hour = series.groupby(series.index.hour).mean()
    if len(by_hour) == 0:
        return None
    ranked = by_hour.sort_values(ascending=False)
    overall_mean = float(series.mean())
    return {
        "peak_hours": [
            {"hour": int(h), "mean": round(float(v), 3)}
            for h, v in ranked.head(3).items()
        ],
        "peak_to_average_ratio": round(float(ranked.iloc[0] / overall_mean), 3)
        if overall_mean else 0.0,
    }


def _distribution_histogram(series: pd.Series, buckets: int = 10) -> list[dict]:
    """Equal-width histogram of consumption values (for distribution insight)."""
    values = series.dropna().to_numpy(dtype=float)
    if len(values) == 0 or values.min() == values.max():
        return []
    lo, hi = float(values.min()), float(values.max())
    width = (hi - lo) / buckets
    edges = [lo + width * i for i in range(buckets + 1)]
    counts, _ = np.histogram(values, bins=edges)
    return [
        {
            "bin": f"{round(edges[i], 2)}–{round(edges[i + 1], 2)}",
            "count": int(counts[i]),
        }
        for i in range(buckets)
        if counts[i] > 0
    ]


def _weather_correlations(series: pd.Series) -> dict | None:
    """Pearson correlations vs real weather, only when timestamps overlap."""
    frame = uf._historical_weather_frame()
    if frame is None or len(frame) == 0:
        return {"available": False, "note": "Historical weather is unavailable for this dataset."}
    base = series.to_frame("consumption")
    joined = base.join(frame[["temperature", "humidity", "precipitation", "wind_speed"]],
                       how="inner")
    if len(joined) < 48:
        return {
            "available": False,
            "note": "Historical weather does not overlap this dataset's timestamps.",
        }
    correlations = []
    for var in ("temperature", "humidity", "precipitation", "wind_speed"):
        corr = float(joined[var].corr(joined["consumption"]))
        correlations.append({
            "variable": var,
            "pearson": round(corr, 4) if np.isfinite(corr) else None,
            "interpretation": _correlation_label(corr) if np.isfinite(corr) else None,
        })
    return {"available": True, "overlap_rows": int(len(joined)), "correlations": correlations}


def _correlation_label(r: float) -> str:
    direction = "positive" if r > 0 else "negative"
    strength = "very weak" if abs(r) < 0.2 else "weak" if abs(r) < 0.4 else "moderate" if abs(r) < 0.7 else "strong"
    return f"{strength} {direction}"


def _rolling_anomalies(series: pd.Series) -> dict:
    """Rolling z-score anomalies vs the local historical average (no forecast)."""
    n = len(series)
    if n < 60:
        return {"available": False,
                "note": "At least ~60 rows of history are required for anomaly detection."}
    deltas = series.index.to_series().diff().dropna()
    mode_seconds = deltas.mode().iloc[0].total_seconds() if len(deltas) else 3600.0
    steps_per_day = 24 if mode_seconds <= 3600 else 1
    window = min(n // 3, max(28, steps_per_day * 7))
    roll_mean = series.rolling(window, center=True, min_periods=window // 2).mean()
    roll_std = series.rolling(window, center=True, min_periods=window // 2).std()
    z = (series - roll_mean) / roll_std.replace(0, np.nan)
    flagged = z.dropna()
    flagged = flagged[flagged.abs() >= 3.0]
    anomalies = []
    for ts, zval in flagged.items():
        severity = "extreme" if abs(zval) >= 4.0 else "high"
        anomalies.append({
            "timestamp": str(ts),
            "observed": round(float(series.loc[ts]), 3),
            "historical_avg": round(float(roll_mean.loc[ts]), 3)
            if pd.notna(roll_mean.loc[ts]) else None,
            "deviation": round(float(series.loc[ts] - roll_mean.loc[ts]), 3),
            "zscore": round(float(zval), 2),
            "severity": severity,
        })
    anomalies = sorted(anomalies, key=lambda a: a["timestamp"])
    return {
        "available": True,
        "window": int(window),
        "threshold": 3.0,
        "count": len(anomalies),
        "anomalies": anomalies[-50:],
    }


def analytics(dataset_id: str | None = None) -> dict:
    """Full household analytics payload for the uploaded dataset."""
    if dataset_id:
        series = upload_service.get_series(dataset_id)
        meta = upload_service.get_metadata(dataset_id)
    else:
        active = _active_household_dataset()
        if active is None:
            raise NotFoundError(ONBOARDING_MESSAGE)
        dataset_id = active["dataset_id"]
        series = upload_service.get_series(dataset_id)
        meta = upload_service.get_metadata(dataset_id)

    freq_label = meta["frequency"]["label"]
    unit = (meta["scope"] or {}).get("unit")

    series = series.sort_index()
    return {
        "dataset_id": dataset_id,
        "filename": meta["filename"],
        "unit": unit,
        "frequency": freq_label,
        "rows": int(len(series)),
        "start_date": str(series.index.min()),
        "end_date": str(series.index.max()),
        "by_hour": _profile(series.groupby(series.index.hour)) if freq_label in SUBDAILY else None,
        "by_day_of_week": [
            {**_r, "day_name": DAY_NAMES.get(_r["value"], "Unknown")}
            for _r in _profile(series.groupby(series.index.dayofweek))
        ],
        "by_month": [
            {**_r, "month_name": MONTH_NAMES.get(_r["value"], "Unknown")}
            for _r in _profile(series.groupby(series.index.month))
        ],
        "monthly_trend": _monthly_trend(series),
        "peak_hours": _peak_hours(series) if freq_label in SUBDAILY else None,
        "distribution": _distribution_histogram(series),
        "weather_correlations": _weather_correlations(series),
        "anomalies": _rolling_anomalies(series),
        "generated_at": cache.utc_now(),
    }