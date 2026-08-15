"""Shared configuration for dataset scripts.

Configuration is driven by environment variables (loaded from a `.env` file
when present) with sensible defaults for the Phase 1 dataset. Nothing here is
hard-coded into the pipeline scripts themselves.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root: <repo>/ml/scripts/config.py -> <repo>
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Load `.env` from the project root if it exists.
load_dotenv(PROJECT_ROOT / ".env")


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, default)
    if value is None or not str(value).strip():
        return default
    return value


# --- Paths -------------------------------------------------------------------
DATA_DIR = Path(_env("DATA_DIR", str(PROJECT_ROOT / "ml" / "data")))
RAW_DIR = Path(_env("RAW_DIR", str(DATA_DIR / "raw")))
PROCESSED_DIR = Path(_env("PROCESSED_DIR", str(DATA_DIR / "processed")))

# --- Dataset configuration ---------------------------------------------------
# Kaggle slug: owner/dataset-name
KAGGLE_DATASET = _env(
    "KAGGLE_DATASET", "nicholasjhana/energy-consumption-generation-prices-and-weather"
)

# Units and scope of the raw consumption series.
# `total load actual` is the hourly average power (MW) over the whole Madrid /
# ENTSO-E regional grid, NOT household consumption. Summing the hourly MW
# values over a period yields energy in MWh; kWh = MWh * KWH_PER_MWH.
CONSUMPTION_UNIT = _env("CONSUMPTION_UNIT", "MW")
ENERGY_UNIT = _env("ENERGY_UNIT", "MWh")
KWH_PER_MWH = int(_env("KWH_PER_MWH", "1000"))
DATA_SCOPE = _env("DATA_SCOPE", "regional grid")

# The main consumption column used for forecasting and validation.
TARGET_COLUMN = _env("TARGET_COLUMN", "total load actual")

# Timestamp column in the raw file.
TIMESTAMP_COLUMN = _env("TIMESTAMP_COLUMN", "time")

# Expected sampling frequency (pandas offset alias), used for gap analysis.
FREQUENCY = _env("FREQUENCY", "h")

# Column used as the primary consumption series for validation/tests.
# In the raw file the target is read from `TARGET_COLUMN`; the cleaned artifact
# always uses `consumption` as the column name.
CLEANED_COLUMN = "consumption"

# Minimum number of records required for a PASS on record sufficiency.
MIN_RECORDS = int(_env("MIN_RECORDS", "20000"))

# Name of the raw file inside the downloaded Kaggle folder that holds the main
# hourly consumption series.
RAW_FILE = _env("RAW_FILE", "energy_dataset.csv")

# Output artifacts
QUALITY_REPORT = PROCESSED_DIR / "quality_report.json"
CLEANED_DATA = PROCESSED_DIR / "consumption_hourly.parquet"

# Expected columns in the raw consumption file (Phase 1 scope: consumption only,
# plus a couple of columns used in EDA correlations).
REQUIRED_COLUMNS = [TIMESTAMP_COLUMN, TARGET_COLUMN]

# ---------------------------------------------------------------------------
# Phase 2: feature engineering + baseline forecasting
# ---------------------------------------------------------------------------
# Chronological split ratios. Must sum to 1.0. Applied after the leading
# warm-up window (max lag / rolling window) is dropped.
TRAIN_RATIO = float(_env("TRAIN_RATIO", "0.70"))
VALIDATION_RATIO = float(_env("VALIDATION_RATIO", "0.15"))
TEST_RATIO = float(_env("TEST_RATIO", "0.15"))

# Window (in hours) used by the moving-average baseline.
MA_WINDOW = int(_env("MA_WINDOW", "24"))

# Split names used as the `split` column value in the features artifact.
SPLIT_TRAIN = "train"
SPLIT_VALIDATION = "validation"
SPLIT_TEST = "test"
SPLITS = [SPLIT_TRAIN, SPLIT_VALIDATION, SPLIT_TEST]

# Lag offsets (hours) and rolling windows (hours) used in feature engineering.
LAG_HOURS = [1, 2, 3, 24, 48, 72, 168]
ROLLING_HOURS = [3, 6, 12, 24, 168]  # 168h == 7 days

# Rolling-window feature names. Hours >= 24 are expressed in days for clarity
# (e.g. 168h -> "rolling_mean_7d") so the artifact matches the spec.
ROLLING_NAME_DAYS = {168: 7}


def rolling_feature_name(hours: int) -> str:
    """Column name for a rolling mean of `hours` hours (e.g. 168 -> ..._7d)."""
    if hours in ROLLING_NAME_DAYS:
        return f"{ROLLING_PREFIX}_{ROLLING_NAME_DAYS[hours]}d"
    return f"{ROLLING_PREFIX}_{hours}h"

# Timestamp-derived features (pandas Timestamp attributes).
TIMESTAMP_FEATURES = [
    "hour",
    "day",
    "day_of_week",
    "day_of_month",
    "week_of_year",
    "month",
    "quarter",
    "year",
    "is_weekend",
]

# Feature column naming schemes.
LAG_PREFIX = "lag"
ROLLING_PREFIX = "rolling_mean"

# Phase 2 output artifacts.
FEATURES_DATA = PROCESSED_DIR / "features_hourly.parquet"
DATA_SPLITS = PROCESSED_DIR / "data_splits.json"
BASELINE_REPORT = PROCESSED_DIR / "baseline_report.json"

# ---------------------------------------------------------------------------
# Phase 3: machine learning forecasting
# ---------------------------------------------------------------------------
# Directory holding serialized model artifacts (gitignored).
MODELS_DIR = Path(_env("MODELS_DIR", str(PROJECT_ROOT / "ml" / "models")))

# Artifact file names.
MODEL_RANDOM_FOREST = MODELS_DIR / "random_forest.joblib"
MODEL_XGBOOST = MODELS_DIR / "xgboost.joblib"
MODEL_METRICS = PROCESSED_DIR / "model_metrics.json"
MODEL_COMPARISON = PROCESSED_DIR / "model_comparison.json"
PREDICTIONS_CSV = PROCESSED_DIR / "predictions.csv"
FORECAST_PLOT = PROCESSED_DIR / "forecast_plot.png"

# Reproducibility: fixed seed for every model / split.
RANDOM_STATE = int(_env("RANDOM_STATE", "42"))

# Model names used in reports / artifacts.
MODEL_RF_NAME = "random_forest"
MODEL_XGB_NAME = "xgboost"
MODEL_BASELINE_PREVIOUS_HOUR = "previous_hour"

# Model names in ranked order (report ordering).
MODEL_NAMES = [MODEL_RF_NAME, MODEL_XGB_NAME]

# Random Forest hyperparameter defaults and search space (validation MAE).
RF_N_ESTIMATORS = int(_env("RF_N_ESTIMATORS", "300"))
RF_MAX_DEPTH = int(_env("RF_MAX_DEPTH", "30"))
RF_MIN_SAMPLES_LEAF = int(_env("RF_MIN_SAMPLES_LEAF", "4"))
RF_N_JOBS = int(_env("RF_N_JOBS", "-1"))

# XGBoost hyperparameter defaults and search space.
XGB_N_ESTIMATORS = int(_env("XGB_N_ESTIMATORS", "600"))
XGB_LEARNING_RATE = float(_env("XGB_LEARNING_RATE", "0.05"))
XGB_MAX_DEPTH = int(_env("XGB_MAX_DEPTH", "8"))
XGB_SUBSAMPLE = float(_env("XGB_SUBSAMPLE", "0.8"))
XGB_COLSAMPLE = float(_env("XGB_COLSAMPLE", "0.8"))
XGB_EARLY_STOPPING_ROUNDS = int(_env("XGB_EARLY_STOPPING_ROUNDS", "30"))

# Number of days of the test set shown in the forecast plot.
FORECAST_PLOT_DAYS = int(_env("FORECAST_PLOT_DAYS", "14"))

# Metrics reported for every model (all computed by forecasting.metrics).
MODEL_METRIC_NAMES = ["mae", "rmse", "mape", "r2"]

# Columns to ignore when building the feature matrix (target + split marker).
NON_FEATURE_COLUMNS = [CLEANED_COLUMN, "split"]

# ---------------------------------------------------------------------------
# Phase 4: weather-aware forecasting
# ---------------------------------------------------------------------------
# Open-Meteo location (stand-in for the ENTSO-E Spain load area) + timezone.
WEATHER_LATITUDE = float(_env("WEATHER_LATITUDE", "40.4168"))
WEATHER_LONGITUDE = float(_env("WEATHER_LONGITUDE", "-3.7038"))
WEATHER_TIMEZONE = _env("WEATHER_TIMEZONE", "Europe/Madrid")

# Open-Meteo hourly variables requested from the archive API.
WEATHER_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "weather_code",
]

# Hourly-weather features added to the model feature matrix. `weather_code` is
# retained raw; `condition` is the derived WMO category, joined at the exact
# consumption timestamp (same hour, no lag / no forward fill).
WEATHER_FEATURES = [
    "temperature",
    "humidity",
    "precipitation",
    "wind_speed",
    "weather_code",
    "condition",
]

# WMO weather-code -> model-readable categories (ordinal, documented).
WEATHER_CONDITIONS = {
    "clear": 0,
    "partly_cloudy": 1,
    "overcast": 2,
    "fog": 3,
    "drizzle": 4,
    "rain": 5,
    "snow": 6,
    "thunderstorm": 7,
}

# Number of days of forecast to fetch when the download script runs.
WEATHER_FORECAST_DAYS = int(_env("WEATHER_FORECAST_DAYS", "7"))

# Open-Meteo caps real future hourly forecasts at 16 days. Anything requested
# beyond this is never fabricated — the snapshot simply covers fewer real days
# and long/medium-term horizons fall back to seasonal patterns with a note.
WEATHER_FORECAST_API_MAX_DAYS = int(_env("WEATHER_FORECAST_API_MAX_DAYS", "16"))

# How old (hours) the persisted Open-Meteo snapshot may be before the API
# attempts to refresh it automatically when a household forecast is generated.
WEATHER_REFRESH_HOURS = float(_env("WEATHER_REFRESH_HOURS", "6"))

# Historical fetch window (padded beyond the consumption period so the merge
# into weather_features.py has full coverage).
WEATHER_START_DATE = _env("WEATHER_START_DATE", "2015-01-01")
WEATHER_END_DATE = _env("WEATHER_END_DATE", "2019-01-01")

# Phase 4 artifacts.
WEATHER_DATA = RAW_DIR / "weather_hourly.parquet"  # historical, local tz
WEATHER_FORECAST = RAW_DIR / "weather_forecast.json"  # current + N-day forecast
WEATHER_FEATURES_DATA = PROCESSED_DIR / "weather_features_hourly.parquet"
WEATHER_COMPARISON = PROCESSED_DIR / "weather_comparison.json"
PREDICTIONS_WEATHER_CSV = PROCESSED_DIR / "predictions_weather.csv"

# Visualization artifacts (Phase 4).
PLOT_TEMP_CONSUMPTION = PROCESSED_DIR / "plot_temperature_vs_consumption.png"
PLOT_HUMIDITY_CONSUMPTION = PROCESSED_DIR / "plot_humidity_vs_consumption.png"
PLOT_WEATHER_CONSUMPTION = PROCESSED_DIR / "plot_weather_vs_consumption.png"
PLOT_WEATHER_FORECAST = PROCESSED_DIR / "plot_weather_forecast.png"

# ---------------------------------------------------------------------------
# Phase 5: peak-hour analysis + anomaly detection
# ---------------------------------------------------------------------------
# Percentile used to define "peak" hours (contiguous runs at/above it).
PEAK_PERCENTILE = float(_env("PEAK_PERCENTILE", "95"))

# Hour-of-day windows defining the morning and evening peak bands.
MORNING_START_HOUR = int(_env("MORNING_START_HOUR", "6"))
MORNING_END_HOUR = int(_env("MORNING_END_HOUR", "11"))
EVENING_START_HOUR = int(_env("EVENING_START_HOUR", "17"))
EVENING_END_HOUR = int(_env("EVENING_END_HOUR", "22"))

# Night hours treated specially for abnormal-nighttime-usage detection.
NIGHT_START_HOUR = int(_env("NIGHT_START_HOUR", "0"))
NIGHT_END_HOUR = int(_env("NIGHT_END_HOUR", "6"))

# Iterated forecast horizon (days) for predicted future peak periods. The
# best consumption-only model is used (weather did not improve Phase 4).
PEAK_FORECAST_DAYS = int(_env("PEAK_FORECAST_DAYS", "14"))
PEAK_FORECAST_MODEL = MODELS_DIR / "consumption_only_xgboost.joblib"

# Anomaly detection configuration.
ANOMALY_ROLLING_WINDOW = int(_env("ANOMALY_ROLLING_WINDOW", "168"))  # 7 days
ANOMALY_ZSCORE_CUTOFF = float(_env("ANOMALY_ZSCORE_CUTOFF", "3.0"))
ANOMALY_NIGHT_ZSCORE_CUTOFF = float(_env("ANOMALY_NIGHT_ZSCORE_CUTOFF", "3.0"))
ANOMALY_IF_CONTAMINATION = float(_env("ANOMALY_IF_CONTAMINATION", "0.01"))
ANOMALY_IF_N_ESTIMATORS = int(_env("ANOMALY_IF_N_ESTIMATORS", "200"))
ANOMALY_IF_RANDOM_STATE = int(_env("ANOMALY_IF_RANDOM_STATE", "42"))

# Phase 5 artifacts.
PEAK_REPORT = PROCESSED_DIR / "peak_analysis.json"
ANOMALY_REPORT = PROCESSED_DIR / "anomaly_report.json"
PEAK_PLOT = PROCESSED_DIR / "peak_hours_plot.png"
ANOMALY_PLOT = PROCESSED_DIR / "anomalies_plot.png"

# ---------------------------------------------------------------------------
# Phase 6: electricity bill and tariff engine
# ---------------------------------------------------------------------------
# Directory holding tariff definitions (ml/tariffs/*.json). Each file fully
# describes a tariff; nothing is hard-coded in the calculation code.
TARIFFS_DIR = Path(_env("TARIFFS_DIR", str(PROJECT_ROOT / "ml" / "tariffs")))

# Default tariff used when `--tariff` is not given.
DEFAULT_TARIFF = _env("DEFAULT_TARIFF", "time_of_use")

# Default currency symbol shown in bill reports.
CURRENCY_SYMBOL = _env("CURRENCY_SYMBOL", "INR")

# Hours per period used for the "monthly estimated bill" projection.
MONTHLY_ESTIMATE_HOURS = int(_env("MONTHLY_ESTIMATE_HOURS", str(30 * 24)))

# Peak-to-off-peak shift percentage for the savings what-if.
PEAK_SHIFT_PERCENT = float(_env("PEAK_SHIFT_PERCENT", "10.0"))

# Directory holding household bill-simulator tariffs (ml/household_tariffs/*.json).
# These are per-kWh residential tariffs, kept fully separate from the regional
# per-MWh tariffs in TARIFFS_DIR.
HOUSEHOLD_TARIFFS_DIR = Path(
    _env("HOUSEHOLD_TARIFFS_DIR", str(PROJECT_ROOT / "ml" / "household_tariffs"))
)

# Scope identifiers used to label every bill result (report + future API).
SCOPE_REGIONAL_GRID = _env("SCOPE_REGIONAL_GRID", "regional_grid")
SCOPE_HOUSEHOLD = _env("SCOPE_HOUSEHOLD", "household")
SCOPE_REGIONAL_LABEL = _env("SCOPE_REGIONAL_LABEL", "Regional Grid Energy Cost")
SCOPE_HOUSEHOLD_LABEL = _env("SCOPE_HOUSEHOLD_LABEL", "Household Bill Simulator")

# Phase 6 artifacts.
BILL_REPORT = PROCESSED_DIR / "bill_report.json"
BILL_HISTORY_CSV = PROCESSED_DIR / "bill_history.csv"
BILL_HISTORY_PLOT = PROCESSED_DIR / "bill_history_plot.png"
PEAK_SHIFT_SAVINGS_CSV = PROCESSED_DIR / "peak_shift_savings_by_month.csv"


def ensure_dirs() -> None:
    """Create data and model directories if they do not exist."""
    for path in (RAW_DIR, PROCESSED_DIR, MODELS_DIR):
        path.mkdir(parents=True, exist_ok=True)
