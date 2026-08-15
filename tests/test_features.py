"""Automated tests for the Phase 2 feature-engineering pipeline and baselines.

Feature functions are tested on small synthetic series for exact-value checks;
the persisted artifacts are tested structurally (columns, chronological split,
no warm-up NaNs, baselines report exists). If the feature matrix or cleaned
series are missing, the artifact-level tests are skipped with a clear message.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT / "ml" / "scripts"))

import baselines  # noqa: E402
import config  # noqa: E402
import feature_engineering as fe  # noqa: E402


@pytest.fixture(scope="module")
def features() -> pd.DataFrame:
    if not config.FEATURES_DATA.exists():
        pytest.skip(
            "feature artifact missing. Run `python ml/scripts/feature_engineering.py` first."
        )
    df = pd.read_parquet(config.FEATURES_DATA)
    df.index = pd.to_datetime(df.index)
    return df


@pytest.fixture()
def synth_series() -> pd.Series:
    idx = pd.date_range("2020-01-01", periods=1000, freq="h")
    values = np.arange(len(idx), dtype=float) * 0.5 + 100.0
    return pd.Series(values, index=idx, name="consumption")


# ---------------------------------------------------------------------------
# 1. Timestamp-based features
# ---------------------------------------------------------------------------
def test_timestamp_features_present(features: pd.DataFrame) -> None:
    missing = [c for c in config.TIMESTAMP_FEATURES if c not in features.columns]
    assert missing == [], f"missing timestamp features: {missing}"


def test_timestamp_feature_values(features: pd.DataFrame) -> None:
    idx = features.index
    assert (features["hour"] == idx.hour).all()
    assert (features["day"] == idx.day).all()
    assert (features["day_of_week"] == idx.dayofweek).all()
    assert (features["day_of_month"] == idx.day).all()
    assert (features["week_of_year"] == idx.isocalendar().week.astype(int)).all()
    assert (features["month"] == idx.month).all()
    assert (features["quarter"] == idx.quarter).all()
    assert (features["year"] == idx.year).all()


def test_timestamp_features_on_synthetic(synth_series: pd.Series) -> None:
    df = fe.add_timestamp_features(synth_series.to_frame("consumption"))
    idx = synth_series.index
    assert (df["hour"] == idx.hour).all()
    assert (df["day_of_week"] == idx.dayofweek).all()
    assert (df["is_weekend"] == (idx.dayofweek >= 5)).all()


# ---------------------------------------------------------------------------
# 2. Lag features
# ---------------------------------------------------------------------------
def test_lag_features_present(features: pd.DataFrame) -> None:
    expected = [f"{config.LAG_PREFIX}_{h}" for h in config.LAG_HOURS]
    missing = [c for c in expected if c not in features.columns]
    assert missing == [], f"missing lag features: {missing}"


def test_lag_values_on_synthetic(synth_series: pd.Series) -> None:
    df = fe.add_lag_features(synth_series.to_frame("consumption"), "consumption")
    for hours in config.LAG_HOURS:
        col = f"{config.LAG_PREFIX}_{hours}"
        expected = synth_series.shift(hours)
        mask = expected.notna()
        pd.testing.assert_series_equal(df[col][mask], expected[mask], check_names=False)


# ---------------------------------------------------------------------------
# 3. Rolling features
# ---------------------------------------------------------------------------
def test_rolling_features_present(features: pd.DataFrame) -> None:
    expected = [config.rolling_feature_name(h) for h in config.ROLLING_HOURS]
    missing = [c for c in expected if c not in features.columns]
    assert missing == [], f"missing rolling features: {missing}"


def test_rolling_values_on_synthetic(synth_series: pd.Series) -> None:
    df = fe.add_rolling_features(synth_series.to_frame("consumption"), "consumption")
    for hours in config.ROLLING_HOURS:
        col = config.rolling_feature_name(hours)
        expected = synth_series.shift(1).rolling(hours).mean()
        mask = expected.notna()
        pd.testing.assert_series_equal(df[col][mask], expected[mask], check_names=False)


# ---------------------------------------------------------------------------
# 4. Chronological train/validation/test split (no shuffle)
# ---------------------------------------------------------------------------
def test_split_columns_and_labels(features: pd.DataFrame) -> None:
    assert "split" in features.columns
    assert set(features["split"].unique()) == set(config.SPLITS)


def test_split_is_chronological(features: pd.DataFrame) -> None:
    train = features[features["split"] == config.SPLIT_TRAIN]
    valid = features[features["split"] == config.SPLIT_VALIDATION]
    test = features[features["split"] == config.SPLIT_TEST]
    assert train.index.is_monotonic_increasing
    assert valid.index.is_monotonic_increasing
    assert test.index.is_monotonic_increasing
    assert train.index.max() < valid.index.min(), "train/validation overlap or misorder"
    assert valid.index.max() < test.index.min(), "validation/test overlap or misorder"


def test_split_is_exhaustive_and_disjoint(features: pd.DataFrame) -> None:
    assert int(features["split"].value_counts().sum()) == len(features)
    assert features.index.is_unique, "duplicate timestamps across splits"


def test_split_ratios(features: pd.DataFrame) -> None:
    n = len(features)
    assert abs(features["split"].eq(config.SPLIT_TRAIN).sum() - int(n * config.TRAIN_RATIO)) <= 1
    assert abs(features["split"].eq(config.SPLIT_VALIDATION).sum() - int(n * config.VALIDATION_RATIO)) <= 1


def test_chronological_split_on_synthetic() -> None:
    idx = pd.date_range("2020-01-01", periods=100, freq="h")
    df = pd.DataFrame({"consumption": np.arange(100.0)}, index=idx)
    train, valid, test = fe.chronological_split(df)
    assert len(train) == 70 and len(valid) == 15 and len(test) == 15
    assert train.index.max() < valid.index.min() < test.index.min()
    assert not train.index.intersection(valid.index).size
    assert not valid.index.intersection(test.index).size
    assert train.index.is_monotonic_increasing


def test_chronological_split_rejects_bad_ratios() -> None:
    idx = pd.date_range("2020-01-01", periods=10, freq="h")
    df = pd.DataFrame({"consumption": np.arange(10.0)}, index=idx)
    with pytest.raises(ValueError):
        fe.chronological_split(df, train_ratio=0.5, validation_ratio=0.2)  # sums to 0.7, not 1.0


# ---------------------------------------------------------------------------
# 5. Baselines
# ---------------------------------------------------------------------------
def test_previous_hour_predictions() -> None:
    s = pd.Series([10.0, 20.0, 30.0, 40.0])
    pd.testing.assert_series_equal(
        baselines.previous_hour_predictions(s),
        pd.Series([np.nan, 10.0, 20.0, 30.0]),
        check_names=False,
    )


def test_previous_day_predictions() -> None:
    values = np.arange(28, dtype=float)
    s = pd.Series(values)
    pred = baselines.previous_day_predictions(s)
    assert np.isnan(pred.iloc[:24]).all()
    for i in range(24, 28):
        assert pred.iloc[i] == values[i - 24]


def test_moving_average_predictions() -> None:
    s = pd.Series([2.0, 4.0, 6.0, 8.0])
    pred = baselines.moving_average_predictions(s, window=2)
    assert np.isnan(pred.iloc[0]) and np.isnan(pred.iloc[1])
    assert pred.iloc[2] == 3.0  # mean of [2.0, 4.0]
    assert pred.iloc[3] == 5.0  # mean of [4.0, 6.0]


def test_moving_average_does_not_leak_current_value() -> None:
    s = pd.Series([100.0, 1.0, 1.0, 1.0])
    pred = baselines.moving_average_predictions(s, window=2)
    assert pred.iloc[2] == 50.5  # mean of [100.0, 1.0]; current value 1.0 excluded


# ---------------------------------------------------------------------------
# 6. Metrics
# ---------------------------------------------------------------------------
def test_mae() -> None:
    actual = np.array([1.0, 2.0, 3.0])
    predicted = np.array([1.5, 2.5, 2.5])
    assert baselines.mae(actual, predicted) == pytest.approx(0.5)


def test_rmse() -> None:
    actual = np.array([1.0, 2.0, 3.0, 4.0])
    predicted = np.array([3.0, 4.0, 5.0, 6.0])
    assert baselines.rmse(actual, predicted) == pytest.approx(2.0)


def test_mape() -> None:
    actual = np.array([100.0, 200.0])
    predicted = np.array([110.0, 180.0])
    assert baselines.mape(actual, predicted) == pytest.approx(10.0)


def test_evaluate_drops_non_finite() -> None:
    actual = np.array([1.0, np.nan, 3.0])
    predicted = np.array([np.nan, 2.0, 3.0])
    result = baselines.evaluate(actual, predicted)
    assert result["mae"] == pytest.approx(0.0)  # only the (3, 3) pair survives


# ---------------------------------------------------------------------------
# 7. Artifacts
# ---------------------------------------------------------------------------
def test_baseline_report_exists() -> None:
    assert config.BASELINE_REPORT.exists(), (
        "baseline_report.json missing. Run `python ml/scripts/baselines.py` first."
    )


def test_no_nan_in_wide_features(features: pd.DataFrame) -> None:
    wide = [f"{config.LAG_PREFIX}_168", config.rolling_feature_name(168)]
    assert features[wide].notna().all().all(), "NaN found in lag_168 / rolling_mean_7d"
