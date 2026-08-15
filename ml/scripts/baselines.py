"""Phase 2: baseline forecasting methods and their evaluation.

Implements three naive forecasting baselines for the hourly consumption series:

  * previous_hour    -> prediction for hour t is the value at hour t-1
  * previous_day     -> prediction for hour t is the value at hour t-24
  * moving_average   -> prediction for hour t is the mean of the previous
                        MA_WINDOW hours (default 24)

Each baseline is evaluated on the validation and test splits produced by
feature_engineering.py using MAE, RMSE and MAPE. Results are written to
ml/data/processed/baseline_report.json.
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
    FEATURES_DATA,
    MA_WINDOW,
    SPLIT_TEST,
    SPLIT_VALIDATION,
    ensure_dirs,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("baselines")


def mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean absolute error."""
    return float(np.mean(np.abs(actual - predicted)))


def rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Root mean squared error."""
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))


def mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean absolute percentage error (%)."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    mask = actual != 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100.0)


def evaluate(actual: np.ndarray, predicted: np.ndarray) -> dict:
    """Compute MAE / RMSE / MAPE for one prediction set.

    Pairs where either the actual or predicted value is non-finite (e.g. the
    leading warm-up rows where a baseline has no history) are dropped first.
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    mask = np.isfinite(actual) & np.isfinite(predicted)
    actual, predicted = actual[mask], predicted[mask]
    if len(actual) == 0:
        return {"mae": float("nan"), "rmse": float("nan"), "mape": float("nan")}
    return {
        "mae": round(mae(actual, predicted), 2),
        "rmse": round(rmse(actual, predicted), 2),
        "mape": round(mape(actual, predicted), 2),
    }


def previous_hour_predictions(series: pd.Series) -> pd.Series:
    """Persistence baseline: forecast hour t with the value from hour t-1."""
    return series.shift(1)


def previous_day_predictions(series: pd.Series) -> pd.Series:
    """Same-hour-previous-day baseline: forecast hour t with value from t-24."""
    return series.shift(24)


def moving_average_predictions(series: pd.Series, window: int = MA_WINDOW) -> pd.Series:
    """Rolling-mean baseline: forecast hour t with the mean of the previous
    `window` hours (backward-looking, so no current value is used)."""
    return series.shift(1).rolling(window).mean()


def baseline_predictions(series: pd.Series) -> dict[str, pd.Series]:
    """Return predictions for every baseline on a full series."""
    return {
        "previous_hour": previous_hour_predictions(series),
        "previous_day": previous_day_predictions(series),
        "moving_average": moving_average_predictions(series, window=MA_WINDOW),
    }


def main() -> int:
    ensure_dirs()
    if not FEATURES_DATA.exists():
        log.error(
            "%s missing. Run `python ml/scripts/feature_engineering.py` first.",
            FEATURES_DATA,
        )
        return 1

    df = pd.read_parquet(FEATURES_DATA)
    df.index = pd.to_datetime(df.index)
    series = df[CLEANED_COLUMN]

    preds = baseline_predictions(series)

    results: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "moving_average_window_hours": MA_WINDOW,
        "metrics": ["mae", "rmse", "mape"],
        "baselines": {},
    }

    for baseline, p in preds.items():
        baseline_results: dict = {}
        for split_name in (SPLIT_VALIDATION, SPLIT_TEST):
            idx = df.index[df["split"] == split_name]
            actual = series.loc[idx].to_numpy()
            predicted = p.reindex(idx).to_numpy()
            baseline_results[split_name] = evaluate(actual, predicted)
        results["baselines"][baseline] = baseline_results

    # Combined validation + test rows for ranking the best baseline.
    eval_splits = df[df["split"].isin((SPLIT_VALIDATION, SPLIT_TEST))]
    for baseline in preds:
        p = preds[baseline]
        actual = eval_splits[CLEANED_COLUMN].to_numpy()
        predicted = p.reindex(eval_splits.index).to_numpy()
        results["baselines"][baseline]["overall_val_test"] = {
            "rows": int(len(eval_splits)),
            **evaluate(actual, predicted),
        }

    best = min(
        results["baselines"],
        key=lambda b: results["baselines"][b][SPLIT_TEST]["mae"],
    )
    results["best_baseline"] = {
        "name": best,
        "criterion": "lowest test-set MAE",
    }

    BASELINE_REPORT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    log.info("Baseline report written to %s", BASELINE_REPORT)
    log.info("Best baseline (lowest test MAE): %s", best)
    return 0


if __name__ == "__main__":
    sys.exit(main())
