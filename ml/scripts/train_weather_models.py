"""Phase 4: retrain + evaluate the weather-aware forecast model.

Trains two XGBoost models with *identical* Phase 3 hyperparameter tuning
(early stopping on the validation split), differing only in features:

  * consumption_only -> the Phase 3 feature matrix (timestamp + lag + rolling)
  * weather_aware    -> the same features plus the Phase 4 weather features

Both use the same chronological train/validation/test splits (no shuffling).
The comparison answers the Phase 4 question: does weather actually improve
forecasting accuracy?

Persists:
  * ml/models/consumption_only_xgboost.joblib
  * ml/models/weather_aware_xgboost.joblib
  * ml/data/processed/weather_comparison.json (metrics + deltas + verdict)
  * ml/data/processed/predictions_weather.csv  (val+test actuals & preds)
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
from train_models import tune_xgboost

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("train_weather_models")

# Model names (as written into the comparison report).
CONSUMPTION_ONLY = "consumption_only"
WEATHER_AWARE = "weather_aware"
MODEL_VARIANTS = [CONSUMPTION_ONLY, WEATHER_AWARE]


def _improvement(summary: dict, split_name: str) -> dict:
    """Delta/percentage improvement of weather_aware over consumption_only.

    MAE / RMSE / MAPE are lower-is-better; R2 is higher-is-better, so the sign
    of its relative change is flipped.
    """
    base = summary["models"][CONSUMPTION_ONLY]["splits"][split_name]
    aware = summary["models"][WEATHER_AWARE]["splits"][split_name]
    out: dict = {}
    for metric in config.MODEL_METRIC_NAMES:
        if not base[metric]:
            out[f"{metric}_improvement_pct"] = 0.0
            continue
        delta = (base[metric] - aware[metric]) if metric != "r2" else (aware[metric] - base[metric])
        out[f"{metric}_improvement_pct"] = round(delta / base[metric] * 100.0, 2)
    out["weather_improves"] = aware["mae"] < base["mae"]
    return out


def train_weather_variants() -> dict:
    """Train both variants and return the comparison summary."""
    config.ensure_dirs()
    if not config.WEATHER_FEATURES_DATA.exists():
        raise FileNotFoundError(
            f"{config.WEATHER_FEATURES_DATA} missing. Run "
            "`python ml/scripts/weather_features.py` first."
        )
    df = forecasting.load_features()
    wf = pd.read_parquet(config.WEATHER_FEATURES_DATA)
    wf.index = pd.to_datetime(wf.index)

    base_features = [c for c in forecasting.feature_columns(df)]
    weather_features = config.WEATHER_FEATURES
    assert set(weather_features) <= set(wf.columns), "weather columns missing"
    assert wf.index.equals(df.index), "weather feature matrix must share the index"

    splits = forecasting.split_by_labels(wf)
    Xd = {config.SPLIT_TRAIN: splits[config.SPLIT_TRAIN][0],
          config.SPLIT_VALIDATION: splits[config.SPLIT_VALIDATION][0],
          config.SPLIT_TEST: splits[config.SPLIT_TEST][0]}
    yd = {config.SPLIT_TRAIN: splits[config.SPLIT_TRAIN][1],
          config.SPLIT_VALIDATION: splits[config.SPLIT_VALIDATION][1],
          config.SPLIT_TEST: splits[config.SPLIT_TEST][1]}

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "location": {
            "latitude": config.WEATHER_LATITUDE,
            "longitude": config.WEATHER_LONGITUDE,
            "timezone": config.WEATHER_TIMEZONE,
        },
        "weather_variables": config.WEATHER_VARIABLES,
        "weather_features": weather_features,
        "base_features": base_features,
        "metrics": config.MODEL_METRIC_NAMES,
        "criterion": "best model = lowest validation MAE",
        "splits_used": {
            label: {
                "rows": int(len(Xd[label])),
                "start": str(Xd[label].index.min()),
                "end": str(Xd[label].index.max()),
            }
            for label in config.SPLITS
        },
        "models": {},
    }

    predictions: list[pd.DataFrame] = []

    for variant in MODEL_VARIANTS:
        feature_cols = base_features + (weather_features if variant == WEATHER_AWARE else [])
        model, chosen = tune_xgboost(Xd[config.SPLIT_TRAIN][feature_cols], yd[config.SPLIT_TRAIN],
                                     Xd[config.SPLIT_VALIDATION][feature_cols], yd[config.SPLIT_VALIDATION])
        artifact = config.MODELS_DIR / f"{variant}_xgboost.joblib"
        joblib.dump(model, artifact)
        log.info("Saved %s -> %s (features=%d)", variant, artifact, len(feature_cols))

        summary["models"][variant] = {
            "model": variant,
            "artifact": str(artifact),
            "feature_count": len(feature_cols),
            "hyperparameters": {
                "max_depth": getattr(model, "max_depth", None),
                "learning_rate": getattr(model, "learning_rate", None),
                "early_stopping_rounds": config.XGB_EARLY_STOPPING_ROUNDS,
            },
            "splits": {},
        }
        for split_name in (config.SPLIT_VALIDATION, config.SPLIT_TEST):
            actual = yd[split_name].to_numpy()
            predicted = model.predict(Xd[split_name][feature_cols])
            summary["models"][variant]["splits"][split_name] = forecasting.metrics(
                actual, predicted
            )
            predictions.append(pd.DataFrame({
                "timestamp": yd[split_name].index,
                "split": split_name,
                "actual": actual,
                variant: predicted,
            }))

    preds_df = pd.concat(predictions).sort_values("timestamp").reset_index(drop=True)
    preds_df.to_csv(config.PREDICTIONS_WEATHER_CSV, index=False)

    summary["comparison"] = {
        split_name: _improvement(summary, split_name)
        for split_name in (config.SPLIT_VALIDATION, config.SPLIT_TEST)
    }

    best = min(
        summary["models"],
        key=lambda n: summary["models"][n]["splits"][config.SPLIT_VALIDATION]["mae"],
    )
    summary["best_model"] = {
        "name": best,
        "validation": summary["models"][best]["splits"][config.SPLIT_VALIDATION],
        "test": summary["models"][best]["splits"][config.SPLIT_TEST],
    }

    config.WEATHER_COMPARISON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info("Weather comparison written to %s", config.WEATHER_COMPARISON)
    log.info("Best variant: %s (validation MAE %.2f)", best,
             summary["best_model"]["validation"]["mae"])
    for split_name in (config.SPLIT_VALIDATION, config.SPLIT_TEST):
        comp = summary["comparison"][split_name]
        log.info(
            "%s | consumption-only MAE %.2f -> weather-aware MAE %.2f (%+.2f%%)",
            split_name,
            summary["models"][CONSUMPTION_ONLY]["splits"][split_name]["mae"],
            summary["models"][WEATHER_AWARE]["splits"][split_name]["mae"],
            comp["mae_improvement_pct"],
        )
    return summary


def main() -> int:
    try:
        train_weather_variants()
    except (FileNotFoundError, ValueError) as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())