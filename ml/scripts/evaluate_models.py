"""Phase 3: final model comparison report + forecast visualization.

Loads the Phase 3 trained models (ml/models/*.joblib) and the Phase 2 baseline
report, recomputes MAE / RMSE / MAPE / R2 for every model AND baseline on the
validation and test splits (chronological, no shuffling), and writes:

  * ml/data/processed/model_comparison.json -> models tested, metrics table,
    best model (lowest validation MAE), training/test periods
  * ml/data/processed/forecast_plot.png      -> actual vs best model vs the
    previous-hour baseline over the last N days of the test split

Run after `python ml/scripts/train_models.py`.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

import joblib
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import baselines  # noqa: E402
import config  # noqa: E402
import forecasting  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("evaluate_models")


def load_models() -> dict[str, object]:
    """Load all Phase 3 trained models from their joblib artifacts."""
    models: dict[str, object] = {}
    for name in config.MODEL_NAMES:
        artifact = config.MODELS_DIR / f"{name}.joblib"
        if not artifact.exists():
            raise FileNotFoundError(
                f"model artifact {artifact} missing. Run "
                "`python ml/scripts/train_models.py` first."
            )
        models[name] = joblib.load(artifact)
    return models


def baseline_predictions(
    series: pd.Series, window: int = config.MA_WINDOW
) -> dict[str, pd.Series]:
    """Recompute the Phase 2 naive baselines on the full consumption series."""
    return {
        config.MODEL_BASELINE_PREVIOUS_HOUR: baselines.previous_hour_predictions(series),
        "previous_day": baselines.previous_day_predictions(series),
        "moving_average": baselines.moving_average_predictions(series, window=window),
    }


def comparison_report() -> dict:
    """Assemble the model-vs-baseline comparison report."""
    config.ensure_dirs()
    df = forecasting.load_features()
    splits = forecasting.split_by_labels(df)
    models = load_models()
    series = df[config.CLEANED_COLUMN]
    baseline_preds = baseline_predictions(series)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "metrics": config.MODEL_METRIC_NAMES,
        "criterion": "best model = lowest validation MAE (test MAE reported separately)",
        "splits_used": {
            label: {
                "rows": int(len(splits[label][0])),
                "start": str(splits[label][0].index.min()),
                "end": str(splits[label][0].index.max()),
            }
            for label in config.SPLITS
        },
        "models": {},
    }

    for name in config.MODEL_NAMES:
        model = models[name]
        report["models"][name] = {"model": name, "splits": {}}
        for split_name in (config.SPLIT_VALIDATION, config.SPLIT_TEST):
            actual = splits[split_name][1].to_numpy()
            predicted = model.predict(splits[split_name][0])
            report["models"][name]["splits"][split_name] = forecasting.metrics(
                actual, predicted
            )

    for name, pred_series in baseline_preds.items():
        report["models"][name] = {"model": name, "kind": "baseline", "splits": {}}
        for split_name in (config.SPLIT_VALIDATION, config.SPLIT_TEST):
            idx = df.index[df["split"] == split_name]
            actual = series.loc[idx].to_numpy()
            predicted = pred_series.reindex(idx).to_numpy()
            report["models"][name]["splits"][split_name] = forecasting.metrics(
                actual, predicted
            )

    best = min(
        (n for n in report["models"] if n in config.MODEL_NAMES),
        key=lambda n: report["models"][n]["splits"][config.SPLIT_VALIDATION]["mae"],
    )
    report["best_model"] = {
        "name": best,
        "validation": report["models"][best]["splits"][config.SPLIT_VALIDATION],
        "test": report["models"][best]["splits"][config.SPLIT_TEST],
    }
    return report


def build_forecast_plot(report: dict, days: int = config.FORECAST_PLOT_DAYS) -> None:
    """Plot actual vs best model vs previous-hour baseline on the test tail."""
    df = forecasting.load_features()
    test = df[df["split"] == config.SPLIT_TEST]
    tail = test.iloc[-days * 24 :]

    best_name = report["best_model"]["name"]
    models = load_models()

    series = df[config.CLEANED_COLUMN]
    prev_hour = baselines.previous_hour_predictions(series).reindex(tail.index)

    fig, ax = plt.subplots(figsize=(14, 5.5))
    ax.plot(tail.index, tail[config.CLEANED_COLUMN], label="Actual", color="#1f77b4", linewidth=1.6)
    if best_name in models:
        ax.plot(
            tail.index,
            models[best_name].predict(tail[forecasting.feature_columns(df)]),
            label=f"Best model ({best_name})",
            color="#d62728",
            linewidth=1.4,
        )
    ax.plot(tail.index, prev_hour, label="Baseline (previous hour)", color="#7f7f7f", linewidth=1.1, alpha=0.9)
    ax.set_title(
        f"Forecast vs Actual — last {days} days of test set\n"
        f"best model: {best_name}"
    )
    ax.set_xlabel("Time")
    ax.set_ylabel("Electricity consumption (MW)")
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    config.FORECAST_PLOT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(config.FORECAST_PLOT, dpi=130)
    plt.close(fig)
    log.info("Forecast plot written to %s", config.FORECAST_PLOT)


def main() -> int:
    try:
        report = comparison_report()
        config.MODEL_COMPARISON.write_text(json.dumps(report, indent=2), encoding="utf-8")
        log.info("Model comparison written to %s", config.MODEL_COMPARISON)
        log.info("Best model: %s (validation MAE %.2f)", report["best_model"]["name"],
                 report["best_model"]["validation"]["mae"])
        build_forecast_plot(report)
    except FileNotFoundError as exc:
        log.error(exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())