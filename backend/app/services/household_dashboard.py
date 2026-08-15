"""Household dashboard service.

Builds a single-screen household view entirely from the *uploaded* datasets and
the shared forecast engine. No synthetic/sample data is ever generated: when no
dataset exists the endpoint reports an onboarding state and the UI shows a call
to action instead of fabricated numbers.

All headline figures (today/tomorrow/week/month totals, peak, bill, weather
status, model, trend) are reused from ``user_forecast._run`` so the dashboard
always agrees with the full forecast report.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..errors import BadRequestError, NotFoundError
from . import upload_service
from . import user_forecast as uf
from . import weather as weather_service

log = logging.getLogger("api.dashboard")

ONBOARDING_MESSAGE = (
    "No household consumption data uploaded yet. Upload a CSV/XLSX file to "
    "unlock your smart energy dashboard."
)

SUBDAILY = ("hourly", "30min", "15min", "minutely")


def _active_household_dataset(limit: int = 5) -> dict | None:
    """Most recent uploaded dataset with a household scope (or None)."""
    for summary in upload_service.recent_datasets(limit):
        if (summary.get("scope") or {}).get("scope") == "household":
            return summary
    return None


def _by_day(points: list[dict]) -> list[tuple[str, float]]:
    """Bucket predicted_consumption into calendar-day totals (ordered)."""
    buckets: dict[str, float] = {}
    for p in points or []:
        day = str(p.get("timestamp"))[:10]
        buckets[day] = buckets.get(day, 0.0) + float(p.get("predicted_consumption") or 0.0)
    return [(day, round(buckets[day], 3)) for day in sorted(buckets)]


def datasets(limit: int = 5) -> dict:
    """Uploaded datasets + which one is the active dashboard dataset."""
    items = upload_service.recent_datasets(limit)
    active_id = None
    for item in items:
        if (item.get("scope") or {}).get("scope") == "household":
            active_id = item["dataset_id"]
            break
    return {"datasets": items, "total": len(items), "active_dataset_id": active_id}


def dashboard(dataset_id: str | None = None) -> dict:
    """Full household dashboard payload (see route docstring for details)."""
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
    scope = (meta["scope"] or {}).get("scope")
    unit = (meta["scope"] or {}).get("unit")

    # Phase 4.1: best-effort auto-refresh of the persisted weather snapshot so
    # the dashboard always has its best available weather (never blocks, never
    # fabricates — see weather_service.ensure_snapshot).
    weather_service.ensure_snapshot()

    # Weekly short-term (weather-aware ML when data allows) + monthly medium-term
    # (always robust, seasonal/trend). The weekly grid is the primary view; the
    # monthly run provides the month total + bill.
    weekly = None
    try:
        weekly = uf._run(dataset_id, 7, "days", None)
    except BadRequestError as exc:  # e.g. too little history for ML warm-up
        log.info("weekly dashboard forecast skipped for %s: %s", dataset_id, exc)
    monthly = uf._run(dataset_id, 30, "days", None)

    view = weekly if weekly is not None else monthly
    granularity = view.get("display_granularity", "daily")
    days_by = _by_day(view.get("points") or [])
    day_labels = [d for d, _ in days_by]

    today = None
    tomorrow = None
    if granularity in SUBDAILY or granularity == "daily":
        today = {
            "date": day_labels[0],
            "value": days_by[0][1],
            "unit": unit,
        }
        if len(days_by) > 1:
            tomorrow = {
                "date": day_labels[1],
                "value": days_by[1][1],
                "unit": unit,
            }

    week_total = None
    if weekly is not None:
        week_total = {
            "start_date": day_labels[0] if day_labels else None,
            "end_date": day_labels[-1] if day_labels else None,
            "total": round(sum(v for _, v in days_by[:7]), 3),
            "average_daily": round(float(weekly["summary"]["average"]), 3)
            if granularity in ("daily",) else round(sum(v for _, v in days_by[:7]) / max(1, len(days_by[:7])), 3),
            "change_percent": weekly["summary"]["change_percent"],
            "unit": unit,
        }

    msum = monthly["summary"]
    month_buckets = _by_day(monthly.get("points") or [])
    month_card = {
        "total": msum["total"],
        "average_daily": round(float(msum["average"]), 3) if granularity == "daily"
        else round(float(msum["total"] / max(1, len(month_buckets))), 3),
        "days": int(msum["periods"]),
        "change_percent": msum["change_percent"],
        "granularity": monthly["display_granularity"],
        "unit": unit,
    }

    # Current / latest readings straight from the uploaded series (no forecast).
    latest_ts = series.index.max()
    latest_value = round(float(series.iloc[-1]), 3)
    tail = series.tail(24) if freq_label in SUBDAILY else series.tail(1)
    current = {
        "timestamp": str(latest_ts),
        "value": latest_value,
        "unit": unit,
        "frequency": freq_label,
        "trailing_total": round(float(tail.sum()), 3),
    }

    peak = view.get("peak") or monthly.get("peak")
    status = view.get("status") or "MEDIUM"
    weather = view.get("weather") or monthly.get("weather")
    classification = (view.get("classification") or
                      monthly.get("classification") or {})
    # Phase 13: compact festival/calendar summary (readable by the AI assistant
    # later; calendar + analysis always computed by the backend engine).
    festivals = view.get("festivals") or monthly.get("festivals")

    return {
        "dataset_id": dataset_id,
        "filename": meta["filename"],
        "scope": scope,
        "unit": unit,
        "energy_unit": meta.get("energy_unit"),
        "frequency": freq_label,
        "rows": int(meta["rows"]),
        "start_date": str(series.index.min()),
        "end_date": str(series.index.max()),
        "current": current,
        "today": today,
        "tomorrow": tomorrow,
        "week": week_total,
        "month": month_card,
        "peak": peak,
        "status": status,
        "model": view.get("model"),
        "model_features": view.get("model_features") or [],
        "trend": (monthly.get("trend") or view.get("trend")),
        "warning": (monthly.get("warning") or view.get("warning") or None),
        "display_label": view.get("display_label"),
        "weather": weather,
        "weather_now": weather_service.current_summary() or {},
        # Explainable household-relative classification stats (readable by the
        # AI assistant later; the classification itself is always computed by
        # the forecast engine, never by the assistant).
        "classification": {
            "status": status,
            "reason": classification.get("reason"),
            "historical_mean": classification.get("historical_mean"),
            "forecast_mean": classification.get("forecast_mean"),
            "forecast_change_percent": classification.get("forecast_change_percent"),
            "historical_90th_percentile": classification.get("historical_90th_percentile"),
            "high_period_count": classification.get("high_period_count"),
            "high_period_percentage": classification.get("high_period_percentage"),
            "forecast_peak": classification.get("forecast_peak"),
            "warning": classification.get("warning"),
        },
        "recommendations": (weekly or monthly).get("recommendations") or [],
        "household_bill": monthly.get("household_bill"),
        "festivals": festivals,
        "points": (weekly or monthly).get("points") or [],
        "historical_tail": (weekly or monthly).get("historical") or [],
        "onboarding": False,
        "generated_at": monthly.get("generated_at"),
    }