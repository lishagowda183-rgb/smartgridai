"""Forecast service: hourly / daily / monthly views of the iterated forecast.

The forecast always comes from ``peak_hours.iterated_forecast`` driven by the
trained best consumption-only model — never from invented values. Hourly
forecasts reuse the cached horizon; daily and monthly views aggregate the same
hourly forecast so every figure is consistent.
"""

from __future__ import annotations

import config as ml_config

from . import cache


def _round_dict(points: list[dict]) -> list[dict]:
    return [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in p.items()} for p in points]


def hourly(hours: int) -> dict:
    """Hourly iterated forecast (MW) for the next `hours` hours."""
    if hours <= 0:
        raise ValueError("hours must be a positive integer")
    forecast = cache.get_forecast(days=max(1, int(hours) // 24))
    points = forecast.head(int(hours))
    return {
        "generated_at": cache.utc_now(),
        "horizon": f"{hours}h",
        "horizon_hours": int(hours),
        "unit": ml_config.CONSUMPTION_UNIT,
        "model": ml_config.PEAK_FORECAST_MODEL.name,
        "start": str(points.index.min()),
        "end": str(points.index.max()),
        "count": int(len(points)),
        "points": [
            {"timestamp": str(ts), "value_mw": round(float(v), 3)}
            for ts, v in points.items()
        ],
    }


def daily(days: int) -> dict:
    """Daily aggregate of the hourly forecast: mean MW + total energy MWh."""
    forecast = cache.get_forecast(days=days)
    mean = forecast.resample("D").mean()
    energy = forecast.resample("D").sum()
    return {
        "generated_at": cache.utc_now(),
        "horizon": f"{days}d",
        "unit": ml_config.CONSUMPTION_UNIT,
        "energy_unit": ml_config.ENERGY_UNIT,
        "model": ml_config.PEAK_FORECAST_MODEL.name,
        "start": str(forecast.index.min()),
        "end": str(forecast.index.max()),
        "count": int(len(mean)),
        "days": [
            {
                "date": str(ts.date()),
                "mean_mw": round(float(m), 3),
                "energy_mwh": round(float(e), 3),
            }
            for ts, (m, e) in zip(mean.index, zip(mean.values, energy.values))
        ],
    }


def monthly(months: int) -> dict:
    """Monthly aggregate of the hourly forecast: mean MW + total energy MWh."""
    forecast = cache.get_forecast(days=months * 30)
    mean = forecast.resample("ME").mean()
    energy = forecast.resample("ME").sum()
    return {
        "generated_at": cache.utc_now(),
        "horizon": f"{months}m",
        "unit": ml_config.CONSUMPTION_UNIT,
        "energy_unit": ml_config.ENERGY_UNIT,
        "model": ml_config.PEAK_FORECAST_MODEL.name,
        "start": str(forecast.index.min()),
        "end": str(forecast.index.max()),
        "count": int(len(mean)),
        "months": [
            {
                "period": str(ts.to_period("M")),
                "mean_mw": round(float(m), 3),
                "energy_mwh": round(float(e), 3),
            }
            for ts, (m, e) in zip(mean.index, zip(mean.values, energy.values))
        ],
    }