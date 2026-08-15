"""Phase 4: download hourly weather data from the Open-Meteo API.

Fetches two things and stores them as artifacts:

  * Historical hourly weather for the configured window via the Open-Meteo
    archive API  -> ml/data/raw/weather_hourly.parquet (Europe/Madrid local tz)
  * Current observations + an N-day hourly forecast via the Open-Meteo forecast
    API          -> ml/data/raw/weather_forecast.json (demo of current+forecast)

Variables: temperature_2m, relative_humidity_2m, precipitation,
wind_speed_10m, weather_code.

Idempotent: skips work when artifacts already exist unless `--force` is given.
Fails cleanly (non-zero exit, no partial artifacts) if the API is unreachable.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

import pandas as pd
import requests

import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("download_weather")

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

REQUEST_TIMEOUT_SECONDS = 60


def _params(daily: bool = False, forecast_days: int | None = None) -> dict[str, object]:
    params: dict[str, object] = {
        "latitude": config.WEATHER_LATITUDE,
        "longitude": config.WEATHER_LONGITUDE,
        "timezone": config.WEATHER_TIMEZONE,
    }
    if daily:
        if forecast_days is None:
            forecast_days = config.WEATHER_FORECAST_DAYS
        params["forecast_days"] = int(
            min(max(int(forecast_days), 1), config.WEATHER_FORECAST_API_MAX_DAYS)
        )
        params["current"] = ",".join(config.WEATHER_VARIABLES)
    params["hourly"] = ",".join(config.WEATHER_VARIABLES)
    return params


def fetch_json(url: str, params: dict[str, object]) -> dict:
    """GET the payload, raising a descriptive error on any failure."""
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        raise ConnectionError(
            f"weather API request failed ({url}). Check internet access and "
            f"retry: {exc}"
        ) from exc


def historical_to_frame(payload: dict) -> pd.DataFrame:
    """Build an hourly DataFrame (local tz index) from an archive payload."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        raise ValueError("archive payload contains no hourly data")
    frame = pd.DataFrame({"time": pd.to_datetime(times)})
    for variable in config.WEATHER_VARIABLES:
        frame[variable] = hourly[variable]
    frame.index = frame.pop("time")
    frame.index.name = "time"
    return frame


def historical_for_range(start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch + return archive hourly weather for an arbitrary date range.

    Used by the household forecast pipeline to obtain real historical weather
    covering an upload's own date span (archive weather is real data only —
    never fabricated). Returns a DataFrame with a local-tz DatetimeIndex and the
    configured WEATHER_VARIABLES columns, or raises ConnectionError/ValueError.
    """
    payload = fetch_json(
        ARCHIVE_URL,
        {
            **_params(),
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    return historical_to_frame(payload)


def download_historical(force: bool = False) -> pd.DataFrame:
    """Fetch + persist the historical hourly weather artifact."""
    if config.WEATHER_DATA.exists() and not force:
        frame = pd.read_parquet(config.WEATHER_DATA)
        log.info("Historical weather already cached: %s (%d rows)", config.WEATHER_DATA, len(frame))
        return frame

    payload = fetch_json(
        ARCHIVE_URL,
        {
            **_params(),
            "start_date": config.WEATHER_START_DATE,
            "end_date": config.WEATHER_END_DATE,
        },
    )
    frame = historical_to_frame(payload)
    config.ensure_dirs()
    frame.to_parquet(config.WEATHER_DATA)
    log.info(
        "Saved historical weather %s -> %s (rows=%d, %s..%s)",
        payload.get("latitude"), config.WEATHER_DATA, len(frame),
        frame.index.min(), frame.index.max(),
    )
    return frame


def download_forecast(force: bool = False) -> dict:
    """Fetch + persist the current-and-forecast demo payload."""
    if config.WEATHER_FORECAST.exists() and not force:
        log.info("Forecast payload already cached: %s", config.WEATHER_FORECAST)
        return json.loads(config.WEATHER_FORECAST.read_text(encoding="utf-8"))

    payload = fetch_json(FORECAST_URL, _params(daily=True))
    payload["_generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    config.ensure_dirs()
    config.WEATHER_FORECAST.write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    log.info("Saved current+%dd forecast -> %s", config.WEATHER_FORECAST_DAYS, config.WEATHER_FORECAST)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download even if cached")
    args = parser.parse_args()

    try:
        frame = download_historical(force=args.force)
        missing = frame[config.WEATHER_VARIABLES].isna().sum().to_dict()
        log.info("Coverage per variable (NaN counts): %s", missing)
        download_forecast(force=args.force)
    except (ConnectionError, ValueError) as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())