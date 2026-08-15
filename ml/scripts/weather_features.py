"""Phase 4: build the weather-augmented feature matrix.

Merges the downloaded hourly weather (ml/data/raw/weather_hourly.parquet, local
Europe/Madrid timestamps) onto the Phase 2/3 feature matrix
(ml/data/processed/features_hourly.parquet) by **exact timestamp equality** —
no lagging, no forward/backward fill, so each row only ever sees the weather
observed at its own hour (exogenous, no future-data leakage).

Adds the Phase 4 weather features (temperature, humidity, precipitation,
wind_speed, weather_code, condition), preserves the existing `split` labels
unchanged, and writes ml/data/processed/weather_features_hourly.parquet.

Fails loudly if the weather data does not cover the consumption grid 100%.
"""

from __future__ import annotations

import logging
import sys

import pandas as pd

import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("weather_features")

# Raw variable -> feature column name.
RAW_TO_FEATURE = {
    "temperature_2m": "temperature",
    "relative_humidity_2m": "humidity",
    "precipitation": "precipitation",
    "wind_speed_10m": "wind_speed",
    "weather_code": "weather_code",
}


def code_to_condition(code: int) -> str:
    """Map a WMO weather code to a coarse category name.

    Open-Meteo uses WMO codes: 0 clear, 1-2 partly cloudy, 3 overcast,
    45-48 fog, 51-67 drizzle/rain, 71-77 snow, 80-82 rain showers,
    85-86 snow showers, 95-99 thunderstorm.
    """
    if 0 <= code <= 1:
        return "clear"
    if code in (2,):
        return "partly_cloudy"
    if code == 3:
        return "overcast"
    if code in (45, 48):
        return "fog"
    if code in (51, 53, 55, 56, 57):
        return "drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "thunderstorm"
    return "clear"


def add_condition_column(frame: pd.DataFrame) -> pd.DataFrame:
    """Derive the ordinal `condition` feature from the raw WMO weather code."""
    frame = frame.copy()
    frame["condition"] = frame["weather_code"].map(
        lambda c: config.WEATHER_CONDITIONS[code_to_condition(int(c))]
    )
    return frame


def load_weather() -> pd.DataFrame:
    """Load the downloaded historical weather with a local-tz index."""
    if not config.WEATHER_DATA.exists():
        raise FileNotFoundError(
            f"{config.WEATHER_DATA} missing. Run `python ml/scripts/download_weather.py` first."
        )
    frame = pd.read_parquet(config.WEATHER_DATA)
    frame.index = pd.to_datetime(frame.index)
    return frame.sort_index()


def merge_weather() -> pd.DataFrame:
    """Merge weather onto the feature matrix, requiring 100% coverage."""
    if not config.FEATURES_DATA.exists():
        raise FileNotFoundError(
            f"{config.FEATURES_DATA} missing. Run "
            "`python ml/scripts/feature_engineering.py` first."
        )
    features = pd.read_parquet(config.FEATURES_DATA)
    features.index = pd.to_datetime(features.index)
    weather = load_weather().rename(columns=RAW_TO_FEATURE)

    aligned = weather.reindex(features.index)
    missing_rows = aligned[config.WEATHER_FEATURES[:5]].isna().all(axis=1).sum()
    if missing_rows:
        raise ValueError(
            f"{missing_rows} consumption hours have no matching weather row. "
            "Re-run the downloader with a wider window / `--force`."
        )

    merged = pd.concat([features, aligned[config.WEATHER_FEATURES[:5]]], axis=1)
    merged = add_condition_column(merged)
    assert set(config.WEATHER_FEATURES) <= set(merged.columns)
    log.info("Weather-aligned rows: %d (exact index match, no shifts)", len(merged))
    log.info("Feature matrix shape: %s", merged.shape)

    merged.to_parquet(config.WEATHER_FEATURES_DATA, index=True)
    log.info("Weather features written to %s", config.WEATHER_FEATURES_DATA)
    return merged


def main() -> int:
    try:
        merge_weather()
    except (FileNotFoundError, ValueError) as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())