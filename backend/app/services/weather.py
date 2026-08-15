"""Weather service: current + hourly forecast from the persisted Open-Meteo JSON.

Read by the API from the raw ``weather_forecast.json`` artifact produced by
``download_weather.py``. Starting Phase 4.1 the API may also *refresh* that
snapshot when it is missing or stale (``ensure_snapshot``) so a household
forecast always has its best available weather — with a safe, retryable failure
mode that never blocks forecasting and never fabricates weather.
"""

from __future__ import annotations

from . import cache


def _condition(code) -> str | None:
    from weather_features import code_to_condition

    if code is None:
        return None
    return code_to_condition(int(code))


def _serialize_observation(row: dict) -> dict:
    return {
        "time": row.get("time"),
        "temperature_c": row.get("temperature_2m"),
        "humidity_pct": row.get("relative_humidity_2m"),
        "precipitation_mm": row.get("precipitation"),
        "wind_speed_kmh": row.get("wind_speed_10m"),
        "weather_code": row.get("weather_code"),
        "condition": _condition(row.get("weather_code")),
    }


def _meta(data: dict) -> dict:
    return {
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "timezone": data.get("timezone"),
        "timezone_abbreviation": data.get("timezone_abbreviation"),
        "elevation": data.get("elevation"),
        "utc_offset_seconds": data.get("utc_offset_seconds"),
        "_generated_at": data.get("_generated_at"),
    }


def _generated_at(data: dict) -> str | None:
    value = data.get("_generated_at")
    return str(value) if value else None


def snapshot_age_hours() -> float | None:
    """Age (hours) of the persisted snapshot, or None when unavailable."""
    try:
        data = cache.load_weather_forecast()
    except Exception:  # noqa: BLE001 - snapshot missing/unreadable
        return None
    from datetime import datetime, timezone

    generated = _generated_at(data)
    try:
        if generated:
            gen = datetime.fromisoformat(generated)
            if gen.tzinfo is None:
                gen = gen.replace(tzinfo=timezone.utc)
            return abs((datetime.now(timezone.utc) - gen).total_seconds()) / 3600.0
    except (TypeError, ValueError):
        pass
    try:
        path = cache.ml_config.WEATHER_FORECAST
        mtime = path.stat().st_mtime
        return abs(datetime.now(timezone.utc).timestamp() - mtime) / 3600.0
    except OSError:
        return None


def ensure_snapshot(force: bool = False, forecast_days: int | None = None) -> dict:
    """Best-effort refresh of the persisted Open-Meteo snapshot.

    No-op when the snapshot exists and is newer than ``WEATHER_REFRESH_HOURS``.
    Refreshes (fetch + persist + cache-invalidate) when missing or stale, and
    never raises: on failure it keeps any existing snapshot (cache fallback) and
    reports ``temporarily_unavailable`` so the forecast continues without
    weather rather than fabricating it. The network fetch is isolated in
    ``_fetch_and_persist`` (monkeypatchable for tests). ``forecast_days``
    sizes the fetch to the current forecast horizon (capped by Open-Meteo).
    """
    try:
        age = snapshot_age_hours()
    except Exception:  # noqa: BLE001
        age = None
    if not force and age is not None and age <= cache.ml_config.WEATHER_REFRESH_HOURS:
        return {"status": "ok", "action": "fresh", "age_hours": round(age, 2)}

    try:
        _fetch_and_persist(forecast_days=forecast_days)
        return {"status": "ok", "action": "refreshed", "age_hours": 0.0}
    except Exception as exc:  # noqa: BLE001 - never block forecasting
        if age is not None:
            return {"status": "cache_fallback", "action": "kept_previous",
                    "age_hours": round(age, 2), "reason": str(exc)}
        return {"status": "temporarily_unavailable", "action": "no_snapshot",
                "reason": str(exc)}


def _fetch_and_persist(forecast_days: int | None = None) -> None:
    """Fetch the fresh Open-Meteo payload and persist it as the snapshot."""
    import json

    import download_weather as dw

    payload = dw.fetch_json(dw.FORECAST_URL, dw._params(daily=True, forecast_days=forecast_days))
    payload["_generated_at"] = cache.utc_now()
    cache.ml_config.ensure_dirs()
    cache.ml_config.WEATHER_FORECAST.write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    cache.invalidate_report_cache(cache.ml_config.WEATHER_FORECAST)


def snapshot_fetched_at() -> str | None:
    """When the persisted snapshot was fetched (ISO), or None."""
    try:
        return _generated_at(cache.load_weather_forecast())
    except Exception:  # noqa: BLE001 - weather simply unavailable
        return None


def archive_frame(start_date: str, end_date: str) -> "pd.DataFrame | None":
    """Real archive hourly weather for an arbitrary date range (or None).

    Wraps ``download_weather.historical_for_range`` so the household pipeline
    can obtain real historical weather covering an upload's own span and keep
    the ML model genuinely weather-aware. Never fabricates; never raises.
    """
    try:
        import download_weather as dw

        frame = dw.historical_for_range(start_date, end_date)
        if frame is None or len(frame) == 0:
            return None
        return frame
    except Exception:  # noqa: BLE001 - weather simply unavailable
        return None


def current_summary() -> dict | None:
    """Compact current observation block (dashboard weather section).

    Returns None (never raises) when the persisted snapshot is unavailable.
    """
    try:
        data = cache.load_weather_forecast()
        cur = data.get("current") or {}
        if not cur:
            return None
        return {
            "generated_at": cache.utc_now(),
            "source": str(cache.ml_config.WEATHER_FORECAST),
            "location": _meta(data),
            "observation": _serialize_observation(cur),
            "_generated_at": _generated_at(data),
        }
    except Exception:  # noqa: BLE001 - weather simply unavailable
        return None


def current() -> dict:
    data = cache.load_weather_forecast()
    cur = data.get("current") or {}
    return {
        "generated_at": cache.utc_now(),
        "source": str(cache.ml_config.WEATHER_FORECAST),
        "location": _meta(data),
        "current": _serialize_observation(cur),
        "_generated_at": data.get("_generated_at"),
    }


def forecast(days: int = 7) -> dict:
    data = cache.load_weather_forecast()
    hourly = data.get("hourly") or {}
    n = max(0, min(int(days) * 24, len(hourly.get("time", []))))
    rows = []
    for i in range(n):
        rows.append(
            _serialize_observation(
                {
                    "time": hourly["time"][i],
                    "temperature_2m": hourly.get("temperature_2m", [None] * n)[i],
                    "relative_humidity_2m": hourly.get("relative_humidity_2m", [None] * n)[i],
                    "precipitation": hourly.get("precipitation", [None] * n)[i],
                    "wind_speed_10m": hourly.get("wind_speed_10m", [None] * n)[i],
                    "weather_code": hourly.get("weather_code", [None] * n)[i],
                }
            )
        )
    return {
        "generated_at": cache.utc_now(),
        "source": str(cache.ml_config.WEATHER_FORECAST),
        "location": _meta(data),
        "requested_days": int(days),
        "returned_hours": int(n),
        "start": rows[0]["time"] if rows else None,
        "end": rows[-1]["time"] if rows else None,
        "points": rows,
    }