"""Demand classification (Phase 11).

Classifies predicted consumption into LOW / MEDIUM / HIGH using thresholds
derived from the uploaded historical distribution — never arbitrary fixed
values. Method (documented in the README + response payload):

    LOW     : below the 33rd percentile of the uploaded history
    MEDIUM  : at/above the 33rd percentile and below the 66th
    HIGH    : at/above the 66th percentile

Every threshold shown in the UI comes from this module (percentiles computed
on the uploaded dataset), so the classification always reflects that dataset.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def thresholds_from_history(series: pd.Series, low_pct: float = 33.0, high_pct: float = 66.0) -> dict:
    """Percentile thresholds derived from the uploaded historical series."""
    values = series.dropna().to_numpy(dtype=float)
    if len(values) == 0:
        return {"low_threshold": 0.0, "high_threshold": 0.0, "method": "percentiles"}
    low = float(np.percentile(values, low_pct))
    high = float(np.percentile(values, high_pct))
    if high < low:
        low, high = high, low
    return {
        "low_threshold": round(low, 4),
        "high_threshold": round(high, 4),
        "method": (
            f"percentiles of the uploaded history "
            f"(p{low_pct:.0f} / p{high_pct:.0f})"
        ),
    }


def classify_value(value: float, thresholds: dict) -> str:
    """Map a single predicted value to LOW / MEDIUM / HIGH."""
    low, high = thresholds["low_threshold"], thresholds["high_threshold"]
    if value < low:
        return "LOW"
    if value >= high:
        return "HIGH"
    return "MEDIUM"


def classify_values(values, thresholds: dict) -> list[str]:
    """Classify a series/list of predicted values."""
    if isinstance(values, pd.Series):
        values = values.tolist()
    return [classify_value(float(v), thresholds) for v in values]


def classification_summary(values, thresholds: dict) -> dict:
    """Counts + percentages per bucket plus the LOW/MEDIUM/HIGH distribution."""
    labels = classify_values(values, thresholds)
    total = max(1, len(labels))
    counts = {name: labels.count(name) for name in ("LOW", "MEDIUM", "HIGH")}
    return {
        "low_threshold": thresholds["low_threshold"],
        "high_threshold": thresholds["high_threshold"],
        "method": thresholds["method"],
        "counts": counts,
        "percentages": {
            name: round(counts[name] / total * 100.0, 1) for name in counts
        },
    }