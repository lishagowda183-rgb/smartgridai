"""Lazy caches for datasets, models and persisted artifacts.

Loading the hourly series, the trained model and the JSON reports on every
request is wasteful, so each accessor returns a module-level singleton. JSON
artifacts are re-read only when the underlying file changes (mtime-based).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import config as ml_config

log = logging.getLogger("api.cache")


def utc_now() -> str:
    """ISO-8601 UTC timestamp used for generated_at fields."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- ML datasets / model ------------------------------------------------------
@lru_cache(maxsize=1)
def get_series():
    """Hourly regional-grid consumption series (MW), sorted, 100% coverage."""
    import bill_engine

    series = bill_engine.load_series()
    log.debug("consumption series cached: n=%d", len(series))
    return series


@lru_cache(maxsize=1)
def get_model():
    """Best consumption-only model used for iterated forecasts."""
    import joblib

    model = joblib.load(ml_config.PEAK_FORECAST_MODEL)
    log.debug("forecast model cached: %s", ml_config.PEAK_FORECAST_MODEL.name)
    return model


@lru_cache(maxsize=64)
def get_forecast(days: int) -> "pd.Series":
    """Iterated hourly forecast of `days` days past the data end (cached per horizon)."""
    import peak_hours as ph

    series = get_series()
    model = get_model()
    forecast = ph.iterated_forecast(series, model, days=days)
    forecast.index = forecast.index.tz_localize(None) if forecast.index.tz is not None else forecast.index
    log.debug("iterated forecast cached: days=%d n=%d", days, len(forecast))
    return forecast


# --- Artifact JSON readers (mtime-aware) ---------------------------------------
_json_store_cache: dict[str, dict] = {}


def load_json(path: Path) -> dict:
    """Read a JSON artifact, re-reading only when the file changes."""
    if not path.exists():
        raise FileNotFoundError(
            f"artifact not found: {path}. Run the corresponding pipeline step first."
        )
    key = f"{path}:{path.stat().st_mtime_ns}"
    if key not in _json_store_cache:
        with path.open("r", encoding="utf-8") as fh:
            _json_store_cache[key] = json.load(fh)
    return _json_store_cache[key]


def load_peak_report() -> dict:
    return load_json(ml_config.PEAK_REPORT)


def load_anomaly_report() -> dict:
    return load_json(ml_config.ANOMALY_REPORT)


def load_bill_report() -> dict:
    return load_json(ml_config.BILL_REPORT)


def load_weather_forecast() -> dict:
    return load_json(ml_config.WEATHER_FORECAST)


def invalidate_report_cache(path: Path) -> None:
    """Drop a cached artifact so the next load re-reads it from disk."""
    if path.exists():
        stat = path.stat().st_mtime_ns
        _json_store_cache.pop(f"{path}:{stat}", None)
