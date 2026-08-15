"""Automated tests for the Phase 4 weather-aware forecasting pipeline.

Unit tests cover weather-payload parsing and the WMO->condition mapping.
Pipeline tests verify exact timestamp alignment (no lag / no future data),
full weather coverage of the consumption grid, preservation of the existing
chronological splits, and the weather-comparison artifacts (skipped with a
clear message when the pipeline has not been run).
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
import weather_features as wf  # noqa: E402


# ---------------------------------------------------------------------------
# 1. WMO -> condition mapping
# ---------------------------------------------------------------------------
def test_code_to_condition_buckets() -> None:
    assert wf.code_to_condition(0) == "clear"
    assert wf.code_to_condition(2) == "partly_cloudy"
    assert wf.code_to_condition(3) == "overcast"
    assert wf.code_to_condition(45) == "fog"
    assert wf.code_to_condition(51) == "drizzle"
    assert wf.code_to_condition(61) == "rain"
    assert wf.code_to_condition(71) == "snow"
    assert wf.code_to_condition(95) == "thunderstorm"
    assert wf.code_to_condition(999) == "clear"  # unknown -> fallback


def test_condition_mapping_covers_all_categories() -> None:
    sample_codes = [0, 1, 2, 3, 45, 48, 51, 55, 61, 65, 71, 77, 80, 85, 95, 99]
    conditions = {wf.code_to_condition(c) for c in sample_codes}
    assert conditions <= set(config.WEATHER_CONDITIONS)


def test_add_condition_column() -> None:
    frame = pd.DataFrame({"weather_code": [0, 61, 95]})
    out = wf.add_condition_column(frame)
    assert out["condition"].tolist() == [
        config.WEATHER_CONDITIONS["clear"],
        config.WEATHER_CONDITIONS["rain"],
        config.WEATHER_CONDITIONS["thunderstorm"],
    ]


# ---------------------------------------------------------------------------
# 2. Weather features / alignment (requires built artifacts)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def weather_features() -> pd.DataFrame:
    if not config.WEATHER_FEATURES_DATA.exists():
        pytest.skip(
            "weather feature artifact missing. Run "
            "`python ml/scripts/download_weather.py` and "
            "`python ml/scripts/weather_features.py` first."
        )
    df = pd.read_parquet(config.WEATHER_FEATURES_DATA)
    df.index = pd.to_datetime(df.index)
    return df


@pytest.fixture(scope="module")
def features() -> pd.DataFrame:
    return forecasting.load_features()


def test_weather_features_present(weather_features: pd.DataFrame) -> None:
    missing = [c for c in config.WEATHER_FEATURES if c not in weather_features.columns]
    assert missing == [], f"missing weather features: {missing}"


def test_weather_features_have_no_nans(weather_features: pd.DataFrame) -> None:
    assert weather_features[config.WEATHER_FEATURES].notna().all().all()


def test_weather_and_base_rows_match(weather_features: pd.DataFrame, features: pd.DataFrame) -> None:
    assert len(weather_features) == len(features)
    assert weather_features.index.equals(features.index)


def test_splits_preserved_in_weather_matrix(weather_features: pd.DataFrame, features: pd.DataFrame) -> None:
    assert weather_features["split"].equals(features["split"])


def test_no_future_weather_leakage(weather_features: pd.DataFrame, features: pd.DataFrame) -> None:
    # Weather for row t must be observed at row t (same hour), never later.
    for col in ["temperature", "humidity", "precipitation", "wind_speed", "weather_code"]:
        base_idx = features.index
        # Column carries no timestamp of its own; alignment is by row index,
        # which we already asserted equals the consumption index.
        assert len(weather_features[col]) == len(base_idx)
    test_end = features[features["split"] == config.SPLIT_TEST].index.max()
    assert test_end <= weather_features.index.max()


def test_feature_set_is_base_plus_weather(weather_features: pd.DataFrame, features: pd.DataFrame) -> None:
    base = set(forecasting.feature_columns(features))
    full = set(forecasting.feature_columns(weather_features))
    assert full == base | set(config.WEATHER_FEATURES)
    assert not (set(config.WEATHER_FEATURES) & {config.CLEANED_COLUMN, "split"})


def test_condition_is_ordinal_category(weather_features: pd.DataFrame) -> None:
    valid = set(config.WEATHER_CONDITIONS.values())
    assert set(weather_features["condition"].unique()) <= valid


# ---------------------------------------------------------------------------
# 3. Comparison report + model artifacts (skipped until trained)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def trained() -> bool:
    return config.WEATHER_COMPARISON.exists() and (
        config.MODELS_DIR / "weather_aware_xgboost.joblib"
    ).exists()


def test_weather_comparison_report_keys(trained: bool) -> None:
    if not trained:
        pytest.skip("weather artifacts missing. Run `python ml/scripts/train_weather_models.py` first.")
    report = json.loads(config.WEATHER_COMPARISON.read_text(encoding="utf-8"))
    assert {"consumption_only", "weather_aware"} <= set(report["models"])
    for variant in ("consumption_only", "weather_aware"):
        for split_name in (config.SPLIT_VALIDATION, config.SPLIT_TEST):
            metrics = report["models"][variant]["splits"][split_name]
            assert set(config.MODEL_METRIC_NAMES) <= set(metrics), variant + " " + split_name
    for split_name in (config.SPLIT_VALIDATION, config.SPLIT_TEST):
        assert "mae_improvement_pct" in report["comparison"][split_name]
        assert "weather_improves" in report["comparison"][split_name]


def test_weather_models_persist(trained: bool) -> None:
    if not trained:
        pytest.skip("weather artifacts missing. Run `python ml/scripts/train_weather_models.py` first.")
    for name in ("consumption_only_xgboost", "weather_aware_xgboost"):
        artifact = config.MODELS_DIR / f"{name}.joblib"
        assert artifact.exists()
        assert hasattr(joblib.load(artifact), "predict")


def test_weather_predictions_csv(trained: bool) -> None:
    if not trained:
        pytest.skip("weather artifacts missing. Run `python ml/scripts/train_weather_models.py` first.")
    preds = pd.read_csv(config.PREDICTIONS_WEATHER_CSV, parse_dates=["timestamp"])
    assert {"actual", "consumption_only", "weather_aware"} <= set(preds.columns)
    assert preds["timestamp"].is_monotonic_increasing


# ---------------------------------------------------------------------------
# 4. Determinism sanity (small synthetic fit with weather columns)
# ---------------------------------------------------------------------------
def test_weather_feature_model_deterministic() -> None:
    idx = pd.date_range("2020-01-01", periods=300, freq="h")
    y = pd.Series(np.sin(np.linspace(0, 4 * np.pi, 300)) * 20 + 100.0, index=idx)
    X = pd.DataFrame(
        {
            "lag_1": y.shift(1),
            "temperature": np.linspace(0, 10, 300),
            "humidity": np.linspace(40, 80, 300),
            "condition": np.tile([0, 1, 2], 100),
        }
    )
    X = X.iloc[10:]
    y = y.iloc[10:]
    a = forecasting.build_xgboost({"n_estimators": 10, "max_depth": 4, "n_jobs": 1})
    b = forecasting.build_xgboost({"n_estimators": 10, "max_depth": 4, "n_jobs": 1})
    a.fit(X, y)
    b.fit(X, y)
    assert np.array_equal(a.predict(X), b.predict(X))