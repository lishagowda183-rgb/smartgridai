"""Phase 3: shared metrics and model factories for ML forecasting.

Provides the four evaluation metrics (MAE / RMSE / MAPE / R2) used by every
forecasting model, factory helpers for the Random Forest and XGBoost regressors
(with values driven by config), and feature-matrix loading. Everything here is
pure and testable on small synthetic inputs; the train/evaluate scripts handle
artifacts and reporting.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import r2_score
from xgboost import XGBRegressor

import baselines
import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("forecasting")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def r2(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Coefficient of determination (R2). NaN if input has <2 pairs.

    Mirrors baselines.evaluate: non-finite pairs are dropped first, so the
    leading warm-up rows never distort the score.
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    mask = np.isfinite(actual) & np.isfinite(predicted)
    actual, predicted = actual[mask], predicted[mask]
    if len(actual) < 2:
        return float("nan")
    return float(r2_score(actual, predicted))


def metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    """Return {mae, rmse, mape, r2} for one prediction set.

    MAE / RMSE / MAPE delegate to baselines (identical semantics, incl. the
    non-finite dropping); R2 is computed on the same surviving pairs.
    """
    result = baselines.evaluate(actual, predicted)
    result["r2"] = round(r2(actual, predicted), 2)
    return result


# ---------------------------------------------------------------------------
# Model factories
# ---------------------------------------------------------------------------
def build_random_forest(params: dict[str, Any] | None = None) -> RandomForestRegressor:
    """Configured Random Forest. `params` overrides the config defaults."""
    base = {
        "n_estimators": config.RF_N_ESTIMATORS,
        "max_depth": config.RF_MAX_DEPTH,
        "min_samples_leaf": config.RF_MIN_SAMPLES_LEAF,
        "n_jobs": config.RF_N_JOBS,
        "random_state": config.RANDOM_STATE,
        "verbose": 0,
    }
    if params:
        base.update(params)
    return RandomForestRegressor(**base)


def build_xgboost(params: dict[str, Any] | None = None) -> XGBRegressor:
    """Configured XGBoost (sklearn API). `params` overrides config defaults."""
    base = {
        "n_estimators": config.XGB_N_ESTIMATORS,
        "learning_rate": config.XGB_LEARNING_RATE,
        "max_depth": config.XGB_MAX_DEPTH,
        "subsample": config.XGB_SUBSAMPLE,
        "colsample_bytree": config.XGB_COLSAMPLE,
        "random_state": config.RANDOM_STATE,
        "n_jobs": config.RF_N_JOBS,
        "verbosity": 0,
    }
    if params:
        base.update(params)
    return XGBRegressor(**base)


# ---------------------------------------------------------------------------
# Feature matrix / splits
# ---------------------------------------------------------------------------
def load_features() -> pd.DataFrame:
    """Load the Phase 2 feature matrix with a datetime index."""
    if not config.FEATURES_DATA.exists():
        raise FileNotFoundError(
            f"feature artifact {config.FEATURES_DATA} missing. Run "
            "`python ml/scripts/feature_engineering.py` first."
        )
    df = pd.read_parquet(config.FEATURES_DATA)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def feature_columns(df: pd.DataFrame) -> list[str]:
    """Return the model feature columns (everything but target and `split`)."""
    return [c for c in df.columns if c not in config.NON_FEATURE_COLUMNS]


def split_by_labels(df: pd.DataFrame) -> dict[str, tuple[pd.DataFrame, pd.Series]]:
    """Chronological X/y per split label, preserving row order."""
    return {
        label: (
            df[df["split"] == label][feature_columns(df)],
            df[df["split"] == label][config.CLEANED_COLUMN],
        )
        for label in config.SPLITS
    }