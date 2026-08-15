"""Phase 2: feature engineering for the hourly electricity-consumption series.

Builds timestamp, lag and rolling features on top of the Phase 1 cleaned
series (ml/data/processed/consumption_hourly.parquet), performs a strictly
chronological train/validation/test split (no shuffling), and persists:

  * ml/data/processed/features_hourly.parquet  -> feature matrix + `split` col
  * ml/data/processed/data_splits.json         -> date ranges + row counts

All lag/rolling features are backward-looking (only past values), so the full
feature matrix can be built once and then split chronologically without any
target leakage into the validation/test sets.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from config import (
    BASELINE_REPORT,
    CLEANED_COLUMN,
    CLEANED_DATA,
    DATA_SPLITS,
    FEATURES_DATA,
    FREQUENCY,
    LAG_HOURS,
    LAG_PREFIX,
    ROLLING_HOURS,
    ROLLING_PREFIX,
    SPLIT_TEST,
    SPLIT_TRAIN,
    SPLIT_VALIDATION,
    TEST_RATIO,
    TIMESTAMP_FEATURES,
    TRAIN_RATIO,
    VALIDATION_RATIO,
    ensure_dirs,
    rolling_feature_name,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("feature_engineering")


def load_cleaned() -> pd.Series:
    """Load the Phase 1 cleaned hourly series (datetime index, `consumption`)."""
    if not CLEANED_DATA.exists():
        raise FileNotFoundError(
            f"cleaned artifact {CLEANED_DATA} missing. Run "
            "`python ml/scripts/validate_dataset.py` first."
        )
    series = pd.read_parquet(CLEANED_DATA)[CLEANED_COLUMN]
    series.index = pd.to_datetime(series.index)
    series = series.sort_index()
    # Reindex onto a complete hourly grid so lags reflect true hour spacing
    # even across the small gaps present in the cleaned series.
    full = pd.date_range(start=series.index.min(), end=series.index.max(), freq=FREQUENCY)
    series = series.reindex(full).dropna()
    return series


def add_timestamp_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add timestamp-derived calendar features from the datetime index."""
    idx = df.index
    ts = pd.DataFrame(index=df.index)
    ts["hour"] = idx.hour
    ts["day"] = idx.day
    ts["day_of_week"] = idx.dayofweek  # Monday=0 ... Sunday=6
    ts["day_of_month"] = idx.day
    ts["week_of_year"] = idx.isocalendar().week.astype(int)
    ts["month"] = idx.month
    ts["quarter"] = idx.quarter
    ts["year"] = idx.year
    ts["is_weekend"] = (idx.dayofweek >= 5).astype(int)
    return pd.concat([df, ts[TIMESTAMP_FEATURES]], axis=1)


def add_lag_features(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Add lag features: value of the target N hours earlier."""
    for hours in LAG_HOURS:
        df[f"{LAG_PREFIX}_{hours}"] = df[target].shift(hours)
    return df


def add_rolling_features(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Add backward-looking rolling means (mean of the previous `w` hours)."""
    for hours in ROLLING_HOURS:
        df[rolling_feature_name(hours)] = df[target].shift(1).rolling(hours).mean()
    return df


def build_feature_frame() -> pd.DataFrame:
    """Assemble the complete feature matrix from the cleaned series."""
    series = load_cleaned()
    df = pd.DataFrame({CLEANED_COLUMN: series})
    df = add_timestamp_features(df)
    df = add_lag_features(df, CLEANED_COLUMN)
    df = add_rolling_features(df, CLEANED_COLUMN)
    return df


def chronological_split(
    df: pd.DataFrame,
    train_ratio: float = TRAIN_RATIO,
    validation_ratio: float = VALIDATION_RATIO,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split chronologically by row order. No shuffling; order preserved."""
    ratios = (train_ratio, validation_ratio)
    if not np.isclose(sum(ratios) + TEST_RATIO, 1.0):
        raise ValueError("train/validation/test ratios must sum to 1.0")
    n = len(df)
    n_train = int(n * train_ratio)
    n_valid = int(n * validation_ratio)
    train = df.iloc[:n_train]
    valid = df.iloc[n_train : n_train + n_valid]
    test = df.iloc[n_train + n_valid :]
    return train, valid, test


def main() -> int:
    ensure_dirs()

    df = build_feature_frame()
    log.info("Feature matrix shape before warm-up drop: %s", df.shape)

    # Drop the leading warm-up rows where the widest lag/rolling feature is
    # still NaN (lag_168 / rolling_mean_7d need 168 prior hours).
    warm_up_cols = [f"{LAG_PREFIX}_168", rolling_feature_name(168)]
    df = df.dropna(subset=warm_up_cols)
    log.info("Feature matrix shape after 168h warm-up drop: %s", df.shape)

    train, valid, test = chronological_split(df)
    parts = {
        SPLIT_TRAIN: train,
        SPLIT_VALIDATION: valid,
        SPLIT_TEST: test,
    }
    for name, part in parts.items():
        parts[name] = part.copy()
        parts[name]["split"] = name
    train, valid, test = parts[SPLIT_TRAIN], parts[SPLIT_VALIDATION], parts[SPLIT_TEST]

    df_out = pd.concat([train, valid, test])
    df_out.to_parquet(FEATURES_DATA, index=True)
    log.info("Features written to %s (%s rows)", FEATURES_DATA, len(df_out))

    splits = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "chronological by row order (no shuffle), ratios "
        f"train={TRAIN_RATIO}, validation={VALIDATION_RATIO}, test={TEST_RATIO}",
        "warm_up_dropped_hours": 168,
        "feature_columns": {
            "timestamp": TIMESTAMP_FEATURES,
            "lags": [f"{LAG_PREFIX}_{h}" for h in LAG_HOURS],
            "rolling": [rolling_feature_name(h) for h in ROLLING_HOURS],
        },
        "splits": {
            SPLIT_TRAIN: {
                "rows": int(len(train)),
                "start": str(train.index.min()),
                "end": str(train.index.max()),
            },
            SPLIT_VALIDATION: {
                "rows": int(len(valid)),
                "start": str(valid.index.min()),
                "end": str(valid.index.max()),
            },
            SPLIT_TEST: {
                "rows": int(len(test)),
                "start": str(test.index.min()),
                "end": str(test.index.max()),
            },
        },
        "artifacts": {
            "features_data": str(FEATURES_DATA),
            "baseline_report": str(BASELINE_REPORT),
        },
    }
    DATA_SPLITS.write_text(json.dumps(splits, indent=2), encoding="utf-8")
    log.info("Split metadata written to %s", DATA_SPLITS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
