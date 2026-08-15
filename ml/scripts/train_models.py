"""Phase 3: train Random Forest and XGBoost forecasters on Phase 2 features.

Loads the feature matrix (ml/data/processed/features_hourly.parquet), fits both
tree models on the training split only (chronological, no shuffling), tunes a
small hyperparameter grid / uses early stopping on the validation split, and
persists:

  * ml/models/random_forest.joblib, ml/models/xgboost.joblib  -> fitted models
  * ml/data/processed/model_metrics.json                       -> per-model
    MAE / RMSE / MAPE / R2 on validation and test, with hyperparameters
  * ml/data/processed/predictions.csv                          -> actuals and
    all model predictions on the validation + test splits

Model selection (lowest validation MAE) is recorded here and finalized by
evaluate_models.py together with the Phase 2 baselines.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd

import config
import forecasting
from baselines import mae  # reused verbatim for hyperparameter selection

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("train_models")

# Fixed hyperparameter search for Random Forest, evaluated on validation MAE.
RF_PARAM_GRID = [
    {"n_estimators": 200, "max_depth": 20, "min_samples_leaf": 4},
    {"n_estimators": 300, "max_depth": 20, "min_samples_leaf": 4},
    {"n_estimators": 300, "max_depth": 30, "min_samples_leaf": 4},
    {"n_estimators": 300, "max_depth": 30, "min_samples_leaf": 8},
]

# Fixed hyperparameter search for XGBoost; each candidate is early-stopped on
# the validation split (no early stopping reuses the full n_estimators).
XGB_PARAM_GRID = [
    {"max_depth": 6, "learning_rate": 0.05},
    {"max_depth": 8, "learning_rate": 0.05},
    {"max_depth": 8, "learning_rate": 0.1},
    {"max_depth": 10, "learning_rate": 0.05},
]


def _record_fitted_params(model, defaults: dict[str, object]) -> dict[str, object]:
    """Snapshot the effective hyperparameters of a fitted model."""
    recorded: dict[str, object] = {}
    for key, default in defaults.items():
        recorded[key] = getattr(model, key, default)
    return recorded


def tune_random_forest(X: pd.DataFrame, y: pd.Series, Xv: pd.DataFrame, yv: pd.Series):
    """Pick the RF config with the lowest validation MAE; return (model, params)."""
    best_model, best_params, best_score = None, None, np.inf
    for params in RF_PARAM_GRID:
        model = forecasting.build_random_forest(params)
        model.fit(X, y)
        score = mae(yv.to_numpy(), model.predict(Xv))
        log.info("RF %s -> validation MAE %.2f", params, score)
        if score < best_score:
            best_model, best_params, best_score = model, params, score
    log.info("Best RF params: %s (validation MAE %.2f)", best_params, best_score)
    return best_model, dict(best_params)


def tune_xgboost(X: pd.DataFrame, y: pd.Series, Xv: pd.DataFrame, yv: pd.Series):
    """Pick the XGB config with the lowest validation MAE (early stopping)."""
    best_model, best_params, best_score = None, None, np.inf
    for params in XGB_PARAM_GRID:
        # xgboost>=3.0 couples early stopping to the constructor; eval_set is
        # still passed to fit().
        model = forecasting.build_xgboost(
            {**params, "n_jobs": 1, "early_stopping_rounds": config.XGB_EARLY_STOPPING_ROUNDS}
        )
        model.fit(X, y, eval_set=[(Xv, yv)], verbose=False)
        score = mae(yv.to_numpy(), model.predict(Xv))
        log.info("XGB %s -> validation MAE %.2f", params, score)
        if score < best_score:
            best_model, best_params, best_score = model, params, score
    if best_model is None:
        raise RuntimeError("XGBoost tuning produced no candidates")
    return best_model, dict(best_params)


def train_and_persist() -> dict:
    """Fit all models, persist them + metrics + predictions, return the summary."""
    config.ensure_dirs()
    df = forecasting.load_features()
    splits = forecasting.split_by_labels(df)

    X, y = splits[config.SPLIT_TRAIN]
    Xv, yv = splits[config.SPLIT_VALIDATION]
    Xt, yt = splits[config.SPLIT_TEST]
    log.info(
        "Training on %d rows across %d features",
        len(X),
        len(forecasting.feature_columns(df)),
    )

    results: dict = {}
    predictions: list[pd.DataFrame] = []

    for name in config.MODEL_NAMES:
        if name == config.MODEL_RF_NAME:
            model, chosen = tune_random_forest(X, y, Xv, yv)
        else:
            model, chosen = tune_xgboost(X, y, Xv, yv)

        artifact = config.MODELS_DIR / f"{name}.joblib"
        joblib.dump(model, artifact)
        log.info("Saved %s -> %s", name, artifact)

        preds = {config.SPLIT_VALIDATION: model.predict(Xv), config.SPLIT_TEST: model.predict(Xt)}
        results[name] = {
            "model": name,
            "artifact": str(artifact),
            "hyperparameters": _record_fitted_params(model, chosen),
            "splits": {},
        }
        for split_name in (config.SPLIT_VALIDATION, config.SPLIT_TEST):
            _actual, _pred = splits[split_name][1].to_numpy(), preds[split_name]
            results[name]["splits"][split_name] = forecasting.metrics(_actual, _pred)
            predictions.append(
                pd.DataFrame(
                    {
                        "timestamp": splits[split_name][1].index,
                        "split": split_name,
                        "actual": _actual,
                        f"{name}": _pred,
                    }
                )
            )

    predictions_df = (
        pd.concat(predictions).sort_values("timestamp").reset_index(drop=True)
    )
    predictions_df.to_csv(config.PREDICTIONS_CSV, index=False)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "metrics": config.MODEL_METRIC_NAMES,
        "feature_columns": forecasting.feature_columns(df),
        "random_state": config.RANDOM_STATE,
        "validation": "chronological by row order (no shuffle)",
        "splits_used": {
            config.SPLIT_TRAIN: {"rows": int(len(X)), "start": str(X.index.min()), "end": str(X.index.max())},
            config.SPLIT_VALIDATION: {"rows": int(len(Xv)), "start": str(Xv.index.min()), "end": str(Xv.index.max())},
            config.SPLIT_TEST: {"rows": int(len(Xt)), "start": str(Xt.index.min()), "end": str(Xt.index.max())},
        },
        "models": {},
    }
    for name in config.MODEL_NAMES:
        summary["models"][name] = results[name]
    # Provisional best by validation MAE; finalized comparison lives in
    # model_comparison.json (evaluate_models.py).
    summary["best_model_by_validation_mae"] = min(
        results, key=lambda n: results[n]["splits"][config.SPLIT_VALIDATION]["mae"]
    )

    config.MODEL_METRICS.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info("Model metrics written to %s", config.MODEL_METRICS)
    return summary


def main() -> int:
    try:
        train_and_persist()
    except FileNotFoundError as exc:
        log.error(exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())