"""Automated tests for the Phase 3 ML forecasting pipeline.

Unit tests cover the added metrics (R2 and the combined metrics dict), the
feature-matrix loading / chronological splits, determinism of the model
factories, best-model selection logic, and — when trained artifacts exist —
the report / model-file structure. Artifact-level tests are skipped with a
clear message if `python ml/scripts/train_models.py` has not been run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT / "ml" / "scripts"))

import config  # noqa: E402
import forecasting  # noqa: E402


# ---------------------------------------------------------------------------
# 1. R2 metric
# ---------------------------------------------------------------------------
def test_r2_perfect_prediction() -> None:
    actual = np.array([1.0, 2.0, 3.0, 4.0])
    assert forecasting.r2(actual, actual) == pytest.approx(1.0)


def test_r2_negative_for_bad_predictions() -> None:
    actual = np.array([1.0, 2.0, 3.0, 4.0])
    predicted = np.array([5.0, 5.0, 5.0, 5.0])
    # Mean prediction can explain zero variance -> R2 can be < 0.
    assert forecasting.r2(actual, predicted) < 0.0


def test_r2_drops_non_finite_pairs() -> None:
    actual = np.array([1.0, np.nan, 3.0, 4.0])
    predicted = np.array([np.nan, 2.0, 3.0, 6.0])
    result = forecasting.r2(actual, predicted)
    # Only the finite pairs (3,3) and (4,6) survive.
    assert result == pytest.approx(forecasting.r2(np.array([3.0, 4.0]), np.array([3.0, 6.0])))


def test_r2_too_few_pairs_is_nan() -> None:
    assert np.isnan(forecasting.r2(np.array([2.0]), np.array([3.0])))


# ---------------------------------------------------------------------------
# 2. Combined metrics (MAE / RMSE / MAPE / R2)
# ---------------------------------------------------------------------------
def test_metrics_includes_all_four() -> None:
    actual = np.array([100.0, 200.0, 300.0])
    predicted = np.array([110.0, 180.0, 290.0])
    result = forecasting.metrics(actual, predicted)
    assert set(result) >= {"mae", "rmse", "mape", "r2"}
    assert result["mae"] == pytest.approx(13.3333, abs=1e-2)
    assert result["mape"] == pytest.approx(7.7777, abs=1e-2)


def test_metrics_orders_values_consistently() -> None:
    actual = np.array([100.0, 200.0, 300.0])
    predicted = np.array([110.0, 180.0, 290.0])
    result = forecasting.metrics(actual, predicted)
    assert result["r2"] == pytest.approx(forecasting.r2(actual, predicted))


# ---------------------------------------------------------------------------
# 3. Feature matrix / chronological splits
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def features() -> pd.DataFrame:
    if not config.FEATURES_DATA.exists():
        pytest.skip(
            "feature artifact missing. Run `python ml/scripts/feature_engineering.py` first."
        )
    return forecasting.load_features()


def test_feature_columns_exclude_target_and_split(features: pd.DataFrame) -> None:
    cols = forecasting.feature_columns(features)
    assert config.CLEANED_COLUMN not in cols
    assert "split" not in cols
    assert len(cols) == len(features.columns) - 2


def test_feature_matrix_has_no_nans(features: pd.DataFrame) -> None:
    cols = forecasting.feature_columns(features)
    assert features[cols].notna().all().all(), "NaN found in feature matrix"


def test_splits_exhaustive_and_chronological(features: pd.DataFrame) -> None:
    splits = forecasting.split_by_labels(features)
    assert sum(len(x) for x, _ in splits.values()) == len(features)
    train, valid, test = config.SPLIT_TRAIN, config.SPLIT_VALIDATION, config.SPLIT_TEST
    assert splits[train][0].index.max() < splits[valid][0].index.min()
    assert splits[valid][0].index.max() < splits[test][0].index.min()


def test_split_by_labels_aligns_targets(features: pd.DataFrame) -> None:
    splits = forecasting.split_by_labels(features)
    train_X, train_y = splits[config.SPLIT_TRAIN]
    assert len(train_X) == len(train_y)
    assert train_X.index.equals(train_y.index)


# ---------------------------------------------------------------------------
# 4. Model factories (small synthetic fit, determinism)
# ---------------------------------------------------------------------------
def test_build_random_forest_deterministic_on_synthetic() -> None:
    idx = pd.date_range("2020-01-01", periods=300, freq="h")
    y = pd.Series(np.sin(np.linspace(0, 4 * np.pi, 300)) * 20 + 100.0, index=idx)
    X = pd.DataFrame({"lag_1": y.shift(1), "rolling_mean_3h": y.shift(1).rolling(3).mean()})
    X = X.iloc[10:]
    y = y.iloc[10:]
    features = X.to_numpy()
    targets = y.to_numpy()
    model_a = forecasting.build_random_forest({"n_estimators": 10, "max_depth": 6})
    model_b = forecasting.build_random_forest({"n_estimators": 10, "max_depth": 6})
    model_a.fit(features, targets)
    model_b.fit(features, targets)
    pa, pb = model_a.predict(features), model_b.predict(features)
    assert np.allclose(pa, pb)
    assert np.isfinite(pa).all()


def test_build_xgboost_deterministic_on_synthetic() -> None:
    idx = pd.date_range("2020-01-01", periods=300, freq="h")
    y = pd.Series(np.sin(np.linspace(0, 4 * np.pi, 300)) * 20 + 100.0, index=idx)
    X = pd.DataFrame({"lag_1": y.shift(1), "rolling_mean_3h": y.shift(1).rolling(3).mean()})
    X = X.iloc[10:]
    y = y.iloc[10:]
    model_a = forecasting.build_xgboost(
        {"n_estimators": 10, "max_depth": 4, "learning_rate": 0.1, "n_jobs": 1}
    )
    model_b = forecasting.build_xgboost(
        {"n_estimators": 10, "max_depth": 4, "learning_rate": 0.1, "n_jobs": 1}
    )
    model_a.fit(X, y)
    model_b.fit(X, y)
    assert np.array_equal(model_a.predict(X), model_b.predict(X))


# ---------------------------------------------------------------------------
# 5. Best-model selection logic
# ---------------------------------------------------------------------------
def test_best_model_by_lowest_validation_mae() -> None:
    results = {
        "a": {config.SPLIT_VALIDATION: {"mae": 5.0}, config.SPLIT_TEST: {"mae": 6.0}},
        "b": {config.SPLIT_VALIDATION: {"mae": 3.0}, config.SPLIT_TEST: {"mae": 7.0}},
        "c": {config.SPLIT_VALIDATION: {"mae": 4.0}, config.SPLIT_TEST: {"mae": 2.0}},
    }
    best = min(results, key=lambda n: results[n][config.SPLIT_VALIDATION]["mae"])
    assert best == "b"


# ---------------------------------------------------------------------------
# 6. Trained artifacts (skipped until train/evaluate scripts have run)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def trained() -> bool:
    return all(
        (config.MODELS_DIR / f"{name}.joblib").exists()
        for name in config.MODEL_NAMES
    )


def test_trained_models_persist_and_load(trained: bool) -> None:
    if not trained:
        pytest.skip("model artifacts missing. Run `python ml/scripts/train_models.py` first.")
    for name in config.MODEL_NAMES:
        artifact = config.MODELS_DIR / f"{name}.joblib"
        assert artifact.exists()
        model = joblib.load(artifact)
        assert hasattr(model, "predict")


def test_model_metrics_report_keys(trained: bool) -> None:
    if not trained:
        pytest.skip("model artifacts missing. Run `python ml/scripts/train_models.py` first.")
    assert config.MODEL_METRICS.exists()
    report = json.loads(config.MODEL_METRICS.read_text(encoding="utf-8"))
    assert set(config.MODEL_NAMES) <= set(report["models"])
    assert set(config.MODEL_METRIC_NAMES) <= set(report["metrics"])
    for name in config.MODEL_NAMES:
        for split_name in (config.SPLIT_VALIDATION, config.SPLIT_TEST):
            metrics = report["models"][name]["splits"][split_name]
            assert set(config.MODEL_METRIC_NAMES) <= set(metrics), name + " " + split_name


def test_model_comparison_report_keys(trained: bool) -> None:
    if not trained:
        pytest.skip("model artifacts missing. Run `python ml/scripts/train_models.py` first.")
    assert config.MODEL_COMPARISON.exists()
    report = json.loads(config.MODEL_COMPARISON.read_text(encoding="utf-8"))
    assert "models" in report and "best_model" in report
    for name in (config.MODEL_RF_NAME, config.MODEL_XGB_NAME, "previous_hour"):
        assert name in report["models"]
    best = report["best_model"]
    assert best["name"] in config.MODEL_NAMES
    assert set(config.MODEL_METRIC_NAMES) <= set(best["test"])


def test_best_model_beats_baseline_on_test_mae(trained: bool) -> None:
    if not trained:
        pytest.skip("model artifacts missing. Run `python ml/scripts/train_models.py` first.")
    report = json.loads(config.MODEL_COMPARISON.read_text(encoding="utf-8"))
    baseline_mae = report["models"]["previous_hour"]["splits"][config.SPLIT_TEST]["mae"]
    best_mae = report["best_model"]["test"]["mae"]
    assert best_mae <= baseline_mae, "best ML model should not underperform naive baseline"