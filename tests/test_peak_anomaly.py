"""Automated tests for the Phase 5 peak-hour analysis and anomaly detection.

Unit tests cover the pure functions on small synthetic series (by-hour means,
max demand, peak-to-average ratio, peak-period contiguity, rolling z-scores,
nighttime detection, severity buckets, isolation-forest execution). Artifact
tests verify the persisted reports and plots and are skipped with a clear
message when the Phase 5 pipeline has not been run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT / "ml" / "scripts"))

import config  # noqa: E402
import anomaly_detection as ad  # noqa: E402
import peak_hours as ph  # noqa: E402


def make_series(periods: int = 30 * 24, base: float = 100.0, amp: float = 20.0) -> pd.Series:
    """Synthetic hourly series with a strong daily cycle peaking at hour 6."""
    idx = pd.date_range("2020-01-01", periods=periods, freq="h")
    hour = idx.hour
    values = base + amp * np.cos(2 * np.pi * (hour - 6) / 24.0)
    return pd.Series(values, index=idx, name=config.CLEANED_COLUMN)


@pytest.fixture(scope="module")
def series() -> pd.Series:
    return make_series()


@pytest.fixture(scope="module")
def features() -> pd.DataFrame:
    if not config.FEATURES_DATA.exists():
        pytest.skip(
            "feature artifact missing. Run `python ml/scripts/feature_engineering.py` first."
        )
    df = pd.read_parquet(config.FEATURES_DATA)
    df.index = pd.to_datetime(df.index)
    return df


# ---------------------------------------------------------------------------
# 1. Peak-hour analysis: pure functions
# ---------------------------------------------------------------------------
def test_average_by_hour_shape_and_range(series: pd.Series) -> None:
    stats = ph.average_by_hour(series)
    assert len(stats) == 24
    assert list(stats.index) == list(range(24))
    assert {"mean_consumption", "median_consumption", "count"} <= set(stats.columns)
    assert (stats["count"] > 0).all()


def test_peak_hour_matches_daily_cycle() -> None:
    idx = pd.date_range("2020-01-01", periods=480, freq="h")
    hour = idx.hour
    # Peak of cos(2pi*(h-6)/24) is at h=6, trough at h=18.
    values = 100.0 + 20.0 * np.cos(2 * np.pi * (hour - 6) / 24.0)
    s = pd.Series(values, index=idx)
    assert ph.peak_hour_of_day(ph.average_by_hour(s)) == 6


def test_max_demand(series: pd.Series) -> None:
    md = ph.max_demand(series)
    assert md["timestamp"] == str(series.idxmax())
    assert md["value"] == pytest.approx(float(series.max()), abs=0.01)


def test_peak_to_average_ratio(series: pd.Series) -> None:
    ratio = ph.peak_to_average_ratio(series)
    assert ratio == pytest.approx(series.max() / series.mean(), abs=0.01)
    assert ratio >= 1.0


def test_morning_evening_windows(series: pd.Series) -> None:
    morning = ph.morning_peaks(series)
    evening = ph.evening_peaks(series)
    assert not morning.empty and not evening.empty
    # In this cycle, the daily max falls in the morning window (peak at 06).
    assert morning["morning_peak"].iloc[0] > evening["evening_peak"].iloc[0]


def test_detect_peak_periods_contiguity() -> None:
    idx = pd.date_range("2020-01-01", periods=100, freq="h")
    values = np.full(100, 50.0)
    values[20:30] = 100.0  # one contiguous peak run, 10 hours
    values[70:73] = 90.0   # a second shorter run
    s = pd.Series(values, index=idx)
    periods = ph.detect_peak_periods(s, percentile=88.0)
    assert len(periods) >= 2
    longest = periods.iloc[0]
    first = s.index[20]
    assert longest["start"] == str(first)
    assert longest["duration_hours"] == 10
    assert longest["peak_value"] == 100.0


# ---------------------------------------------------------------------------
# 2. Anomaly detection: pure functions
# ---------------------------------------------------------------------------
def test_rolling_zscore_identifies_spike() -> None:
    idx = pd.date_range("2020-01-01", periods=500, freq="h")
    hour = np.asarray(idx.hour)
    values = 100.0 + 10.0 * np.cos(2 * np.pi * (hour - 6) / 24.0)
    values = values.copy()
    values[400] = 300.0  # a clear spike
    s = pd.Series(values, index=idx)
    anomalies = ad.rolling_anomalies(s, window=48, cutoff=3.0)
    assert anomalies.iloc[0]["timestamp"] == str(idx[400])
    assert anomalies.iloc[0]["type"] == "spike"
    assert anomalies.iloc[0]["score"] > 3.0


def test_rolling_zscore_identifies_drop() -> None:
    idx = pd.date_range("2020-01-01", periods=500, freq="h")
    hour = np.asarray(idx.hour)
    values = 100.0 + 10.0 * np.cos(2 * np.pi * (hour - 6) / 24.0)
    values = values.copy()
    values[400] = 10.0  # a clear drop
    s = pd.Series(values, index=idx)
    anomalies = ad.rolling_anomalies(s, window=48, cutoff=3.0)
    assert anomalies.iloc[0]["timestamp"] == str(idx[400])
    assert anomalies.iloc[0]["type"] == "drop"
    assert anomalies.iloc[0]["score"] < -3.0


def test_hourly_profile_anomalies() -> None:
    idx = pd.date_range("2020-01-01", periods=720, freq="h")
    hour = np.asarray(idx.hour)
    values = 100.0 + 10.0 * np.cos(2 * np.pi * (hour - 6) / 24.0)
    values = values.copy()
    values[500] = values[500] + 80.0  # large deviation at its hour
    s = pd.Series(values, index=idx)
    anomalies = ad.hourly_profile_anomalies(s, cutoff=3.0)
    assert anomalies.iloc[0]["timestamp"] == str(idx[500])
    assert anomalies.iloc[0]["type"] == "high"


def test_nighttime_anomalies() -> None:
    idx = pd.date_range("2020-01-01", periods=60 * 24, freq="h")
    hour = np.asarray(idx.hour)
    values = 100.0 + 10.0 * np.cos(2 * np.pi * (hour - 6) / 24.0)
    night_mask = (hour >= 0) & (hour <= 5)
    values = np.where(night_mask, 100.0, values)  # flat night baseline
    values[np.where((hour == 2) & (np.arange(len(idx)) // 24 == 30))[0]] = 400.0
    s = pd.Series(values, index=idx)
    anomalies = ad.nighttime_anomalies(s, start_hour=0, end_hour=5, cutoff=3.0)
    assert not anomalies.empty
    assert set(anomalies["method"]) == {"nighttime"}
    assert anomalies["type"].iloc[0] == "abnormal_night_high"


def test_isolation_forest_runs_on_features(features: pd.DataFrame) -> None:
    iso = ad.isolation_forest_anomalies(features[config.CLEANED_COLUMN])
    assert isinstance(iso, pd.DataFrame)
    assert set(iso.columns) <= {"timestamp", "value", "method", "type", "score"}
    if not iso.empty:
        assert (iso["method"] == "isolation_forest").all()
        assert np.isfinite(iso["score"]).all()


def test_severity_buckets() -> None:
    assert ad.severity_of(3.0) == ad.SEVERITY_MODERATE
    assert ad.severity_of(4.5) == ad.SEVERITY_HIGH
    assert ad.severity_of(7.1) == ad.SEVERITY_CRITICAL


def test_combine_anomalies_empty() -> None:
    combined = ad.combine_anomalies(make_series(100), [pd.DataFrame()])
    assert list(combined.columns) == ["timestamp", "value", "method", "type", "score", "severity"]
    assert combined.empty


def test_combine_anomalies_merges_and_sorts() -> None:
    series = make_series(200)
    series.iloc[100] = 500.0
    roll = ad.rolling_anomalies(series, window=48, cutoff=3.0)
    combined = ad.combine_anomalies(series, [roll])
    assert not combined.empty
    assert "severity" in combined.columns
    assert combined["severity"].isin(
        [ad.SEVERITY_MODERATE, ad.SEVERITY_HIGH, ad.SEVERITY_CRITICAL]
    ).all()


# ---------------------------------------------------------------------------
# 3. Artifacts (skipped until run)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def peak_report() -> dict:
    if not config.PEAK_REPORT.exists():
        pytest.skip("peak report missing. Run `python ml/scripts/peak_hours.py` first.")
    return json.loads(config.PEAK_REPORT.read_text(encoding="utf-8"))


def test_peak_report_keys(peak_report: dict) -> None:
    assert "summary" in peak_report
    assert "max_demand" in peak_report["summary"]
    assert "peak_to_average_ratio" in peak_report["summary"]
    assert "average_by_hour" in peak_report
    assert "top_historical_peak_periods" in peak_report
    assert "forecast" in peak_report


def test_predicted_peaks_are_in_the_future(peak_report: dict, features: pd.DataFrame) -> None:
    end = features.index.max()
    periods = peak_report["forecast"]["predicted_future_peak_periods"]
    assert periods, "expected at least one predicted future peak period"
    for period in periods:
        assert pd.to_datetime(period["start"]) > end


def test_peak_plot_exists() -> None:
    assert config.PEAK_PLOT.exists(), "peak_hours_plot.png missing"


@pytest.fixture(scope="module")
def anomaly_report() -> dict:
    if not config.ANOMALY_REPORT.exists():
        pytest.skip("anomaly report missing. Run `python ml/scripts/anomaly_detection.py` first.")
    return json.loads(config.ANOMALY_REPORT.read_text(encoding="utf-8"))


def test_anomaly_report_keys(anomaly_report: dict) -> None:
    assert set(anomaly_report) >= {"counts_by_method", "counts_by_type", "counts_by_severity", "anomalies"}


def test_anomaly_rows_have_required_fields(anomaly_report: dict) -> None:
    required = {"timestamp", "value", "method", "type", "score", "severity"}
    for row in anomaly_report["anomalies"]:
        assert required <= set(row), f"missing fields in {row}"


def test_anomaly_timestamps_in_range(anomaly_report: dict, features: pd.DataFrame) -> None:
    if not anomaly_report["anomalies"]:
        pytest.skip("no anomalies detected")
    ts = pd.to_datetime([a["timestamp"] for a in anomaly_report["anomalies"]])
    assert ts.min() >= features.index.min()
    assert ts.max() <= features.index.max()


def test_anomaly_plot_exists() -> None:
    assert config.ANOMALY_PLOT.exists(), "anomalies_plot.png missing"