"""Automated tests for the Phase 1 dataset.

Tests depend on the downloaded dataset. If the raw file has not been
downloaded (download_dataset.py) or the cleaned artifact has not been produced
(validate_dataset.py), the affected tests are skipped with a clear message so
`pytest` stays green on a clean checkout.
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

import config  # noqa: E402

HOUR = pd.Timedelta(hours=1)


def _find_raw_file() -> Path | None:
    raw_dir = config.RAW_DIR
    candidates = [
        raw_dir / config.RAW_FILE,
        *[d / config.RAW_FILE for d in raw_dir.iterdir() if d.is_dir()],
    ]
    return next((c for c in candidates if c.exists()), None)


def _parse_ts(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, format="mixed").dt.tz_localize(None)


@pytest.fixture(scope="module")
def raw_df() -> pd.DataFrame:
    raw_file = _find_raw_file()
    if raw_file is None:
        pytest.skip(
            f"raw file {config.RAW_FILE!r} not found. Run "
            "`python ml/scripts/download_dataset.py` first."
        )
    return pd.read_csv(raw_file)


@pytest.fixture(scope="module")
def clean_series() -> pd.Series:
    if not config.CLEANED_DATA.exists():
        pytest.skip(
            "cleaned artifact missing. Run `python ml/scripts/validate_dataset.py` first."
        )
    return pd.read_parquet(config.CLEANED_DATA)["consumption"]


# ---------------------------------------------------------------------------
# 1. Required columns exist
# ---------------------------------------------------------------------------
def test_required_columns_exist(raw_df: pd.DataFrame) -> None:
    missing = [c for c in config.REQUIRED_COLUMNS if c not in raw_df.columns]
    assert missing == [], f"missing required columns: {missing}"


# ---------------------------------------------------------------------------
# 2. Timestamp is valid
# ---------------------------------------------------------------------------
def test_timestamp_is_valid(raw_df: pd.DataFrame) -> None:
    ts = _parse_ts(raw_df[config.TIMESTAMP_COLUMN])
    assert ts.isna().sum() == 0, f"{ts.isna().sum()} unparseable timestamps"
    assert pd.api.types.is_datetime64_any_dtype(ts)


def test_timestamps_are_sorted(clean_series: pd.Series) -> None:
    assert clean_series.index.is_monotonic_increasing


# ---------------------------------------------------------------------------
# 3. Consumption is numeric
# ---------------------------------------------------------------------------
def test_consumption_is_numeric(raw_df: pd.DataFrame) -> None:
    col = pd.to_numeric(raw_df[config.TARGET_COLUMN], errors="coerce")
    assert pd.api.types.is_numeric_dtype(col)
    assert col.notna().sum() > 0, "no numeric consumption values parsed"


# ---------------------------------------------------------------------------
# 4. Consumption values are valid
# ---------------------------------------------------------------------------
def test_consumption_values_are_valid(raw_df: pd.DataFrame) -> None:
    col = pd.to_numeric(raw_df[config.TARGET_COLUMN], errors="coerce")
    assert np.isfinite(col.dropna()).all(), "non-finite consumption values present"
    assert (col.dropna() >= 0).all(), "negative consumption values present"


# ---------------------------------------------------------------------------
# 5. Duplicate timestamps are detected
# ---------------------------------------------------------------------------
def test_duplicate_timestamps_are_detected(raw_df: pd.DataFrame) -> None:
    ts = _parse_ts(raw_df[config.TIMESTAMP_COLUMN])
    assert ts.duplicated().sum() == 0, f"{ts.duplicated().sum()} duplicate timestamps"


# ---------------------------------------------------------------------------
# 6. Dataset has sufficient records
# ---------------------------------------------------------------------------
def test_sufficient_records(clean_series: pd.Series) -> None:
    assert len(clean_series) >= config.MIN_RECORDS, (
        f"only {len(clean_series)} records, expected >= {config.MIN_RECORDS}"
    )


# ---------------------------------------------------------------------------
# 7. Sampling frequency is reasonable
# ---------------------------------------------------------------------------
def test_sampling_frequency_reasonable(clean_series: pd.Series) -> None:
    deltas = clean_series.index.to_series().diff().dropna()
    assert deltas.mode().iloc[0] == HOUR, "modal sampling interval is not hourly"
    hourly_pct = float((deltas == HOUR).mean() * 100)
    assert hourly_pct >= 95.0, f"only {hourly_pct:.2f}% of intervals are exactly hourly"


# ---------------------------------------------------------------------------
# Extras
# ---------------------------------------------------------------------------
def test_no_missing_target_in_cleaned(clean_series: pd.Series) -> None:
    assert clean_series.notna().all(), "cleaned series contains missing values"


def test_quality_report_exists() -> None:
    assert config.QUALITY_REPORT.exists(), (
        "quality_report.json missing. Run `python ml/scripts/validate_dataset.py` first."
    )
