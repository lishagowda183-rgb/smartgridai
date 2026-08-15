"""Validate the downloaded electricity-consumption dataset.

Runs a battery of structural and statistical checks against the raw data,
writes a cleaned hourly series to ml/data/processed/consumption_hourly.parquet
and a structured ml/data/processed/quality_report.json containing every check
with a final PASS / WARNING / FAIL status.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    CLEANED_COLUMN,
    CLEANED_DATA,
    FREQUENCY,
    KAGGLE_DATASET,
    MIN_RECORDS,
    PROCESSED_DIR,
    QUALITY_REPORT,
    RAW_DIR,
    RAW_FILE,
    REQUIRED_COLUMNS,
    TARGET_COLUMN,
    TIMESTAMP_COLUMN,
    CONSUMPTION_UNIT,
    DATA_SCOPE,
    ENERGY_UNIT,
    KWH_PER_MWH,
    ensure_dirs,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("validate_dataset")


class Check:
    """A single named quality check with a PASS/WARN/FAIL status."""

    def __init__(self, check_id: str, name: str):
        self.id = check_id
        self.name = name
        self.status = "PASS"
        self.details: dict = {}

    def pass_(self, **details) -> "Check":
        self.status = "PASS"
        self.details = details
        return self

    def warn(self, **details) -> "Check":
        self.status = "WARN"
        self.details = details
        return self

    def fail(self, **details) -> "Check":
        self.status = "FAIL"
        self.details = details
        return self

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "status": self.status, "details": self.details}


def find_raw_file(raw_dir: Path) -> Path | None:
    """Locate the configured raw CSV inside the downloaded dataset folder."""
    candidates = [
        raw_dir / RAW_FILE,
        *[d / RAW_FILE for d in raw_dir.iterdir() if d.is_dir()],
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def parse_timestamps(series: pd.Series) -> pd.Series:
    """Parse timestamps to tz-naive UTC, tolerating mixed/misleading offsets."""
    parsed = pd.to_datetime(series, utc=True, format="mixed")
    return parsed.dt.tz_localize(None)


def main() -> int:
    ensure_dirs()
    checks: list[Check] = []

    raw_file = find_raw_file(RAW_DIR)
    if raw_file is None:
        log.error(
            "Raw file %r not found under %s. Run download_dataset.py first.",
            RAW_FILE,
            RAW_DIR,
        )
        return 1

    log.info("Loading %s", raw_file)
    df = pd.read_csv(raw_file)

    # --- 1. Required columns -------------------------------------------------
    check = Check("required_columns", "Required columns present")
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        check.fail(missing_columns=missing_cols)
    else:
        check.pass_(required_columns=REQUIRED_COLUMNS)
    checks.append(check)

    # --- 2. Data types -------------------------------------------------------
    check = Check("data_types", "Column data types")
    if TIMESTAMP_COLUMN in df.columns:
        ts_sample = df[TIMESTAMP_COLUMN].astype(str).head(5).tolist()
        try:
            _ = parse_timestamps(df[TIMESTAMP_COLUMN])
            ts_ok = True
        except Exception as exc:
            ts_ok = False
            ts_err = str(exc)
        target_numeric = (
            TARGET_COLUMN in df.columns
            and pd.api.types.is_numeric_dtype(df[TARGET_COLUMN].dropna())
        )
        if ts_ok and target_numeric:
            check.pass_(
                timestamp_column=TIMESTAMP_COLUMN,
                timestamp_dtype=str(df[TIMESTAMP_COLUMN].dtype),
                timestamp_sample=ts_sample,
                target_column=TARGET_COLUMN,
                target_dtype=str(df[TARGET_COLUMN].dtype),
            )
        else:
            check.fail(
                timestamp_ok=ts_ok,
                timestamp_error=ts_err if not ts_ok else None,
                target_numeric=target_numeric,
                target_dtype=str(df[TARGET_COLUMN].dtype) if TARGET_COLUMN in df.columns else None,
            )
    else:
        check.fail(error=f"timestamp column {TIMESTAMP_COLUMN!r} missing")
    checks.append(check)

    # Prepare a cleaned frame if required columns are present.
    if not missing_cols and TARGET_COLUMN in df.columns:
        ts = parse_timestamps(df[TIMESTAMP_COLUMN])
        clean = pd.DataFrame(
            {TIMESTAMP_COLUMN: ts, CLEANED_COLUMN: pd.to_numeric(df[TARGET_COLUMN], errors="coerce")}
        ).dropna(subset=[CLEANED_COLUMN])
        clean = clean.sort_values(TIMESTAMP_COLUMN).drop_duplicates(TIMESTAMP_COLUMN).reset_index(drop=True)
        clean = clean.set_index(TIMESTAMP_COLUMN)
        clean.index.name = "timestamp"
    else:
        clean = None

    if clean is None or clean.empty:
        log.error("Unable to build a cleaned consumption series; aborting.")
        return 1

    ts_full = clean.index
    target = clean[CLEANED_COLUMN]
    n_rows, n_cols = df.shape
    n_clean = len(clean)

    # --- 3. Timestamp parsing -------------------------------------------------
    check = Check("timestamp_parsing", "Timestamp parsing")
    if df[TIMESTAMP_COLUMN].astype(str).str.strip().eq("").any():
        check.fail(empty_strings=int(df[TIMESTAMP_COLUMN].astype(str).str.strip().eq("").sum()))
    elif ts_full.isna().any():
        check.fail(nat_timestamps=int(ts_full.isna().sum()))
    else:
        check.pass_(rows_parsed=int(n_clean), format="ISO 8601 with offset tolerance")
    checks.append(check)

    # --- 4. Timestamp ordering (as found in the raw file) ----------------------
    check = Check("timestamp_ordering", "Timestamp ordering")
    raw_ts = parse_timestamps(df[TIMESTAMP_COLUMN])
    if not raw_ts.is_monotonic_increasing:
        check.warn(notes="raw file not sorted; cleaned artifact was sorted")
    else:
        check.pass_()
    checks.append(check)

    # --- 5. Duplicate rows -----------------------------------------------------
    check = Check("duplicate_rows", "Duplicate rows")
    dup_rows = int(df.duplicated().sum())
    if dup_rows == 0:
        check.pass_()
    else:
        check.warn(duplicate_rows=dup_rows, pct=round(dup_rows / n_rows * 100, 4))
    checks.append(check)

    # --- 6. Duplicate timestamps ------------------------------------------------
    check = Check("duplicate_timestamps", "Duplicate timestamps")
    dup_ts = int(raw_ts.duplicated().sum())
    if dup_ts == 0:
        check.pass_()
    else:
        check.fail(duplicate_timestamps=dup_ts, pct=round(dup_ts / n_rows * 100, 4))
    checks.append(check)

    # --- 7. Missing values ------------------------------------------------------
    check = Check("missing_values", "Missing values")
    missing_total = int(df.isna().sum().sum())
    missing_target = int(df[TARGET_COLUMN].isna().sum())
    missing_by_col = {str(k): int(v) for k, v in df.isna().sum().items() if v > 0}
    if missing_target == 0:
        check.pass_(missing_cells=missing_total, missing_target=missing_target)
    elif missing_target / n_rows <= 0.01:
        check.warn(
            missing_cells=missing_total,
            missing_target=missing_target,
            target_missing_pct=round(missing_target / n_rows * 100, 4),
            by_column=missing_by_col,
        )
    else:
        check.fail(
            missing_cells=missing_total,
            missing_target=missing_target,
            target_missing_pct=round(missing_target / n_rows * 100, 4),
            by_column=missing_by_col,
        )
    checks.append(check)

    # --- 8. Invalid consumption values (non-finite) ------------------------------
    check = Check("invalid_consumption", "Invalid consumption values (NaN/inf)")
    raw_target = pd.to_numeric(df[TARGET_COLUMN], errors="coerce")
    inf_count = int(np.isinf(raw_target).sum())
    nan_count = int(raw_target.isna().sum())
    if inf_count == 0 and nan_count == 0:
        check.pass_()
    else:
        check.warn(nan_count=nan_count, inf_count=inf_count)
    checks.append(check)

    # --- 9. Negative consumption -------------------------------------------------
    check = Check("negative_consumption", "Negative consumption")
    neg_count = int((target < 0).sum())
    if neg_count == 0:
        check.pass_()
    else:
        check.fail(negative_count=neg_count, pct=round(neg_count / n_clean * 100, 4))
    checks.append(check)

    # --- 10. Date range -----------------------------------------------------------
    check = Check("date_range", "Date range")
    start, end = ts_full.min(), ts_full.max()
    span_days = (end - start).total_seconds() / 86400.0
    if span_days >= 730:
        check.pass_(start=str(start), end=str(end), span_days=round(span_days, 2))
    else:
        check.warn(start=str(start), end=str(end), span_days=round(span_days, 2), note="short history")
    checks.append(check)

    # --- 11. Sampling frequency -----------------------------------------------------
    check = Check("sampling_frequency", "Sampling frequency")
    deltas = ts_full.to_series().diff().dropna()
    mode_delta = deltas.mode().iloc[0]
    hourly_count = int((deltas == pd.Timedelta(hours=1)).sum())
    pct_hourly = round(hourly_count / len(deltas) * 100, 4)
    freq_ok = mode_delta == pd.Timedelta(hours=1) and pct_hourly >= 95.0
    if freq_ok:
        check.pass_(
            mode_delta=str(mode_delta),
            pct_hourly=pct_hourly,
            top_deltas=[str(d) for d in deltas.value_counts().head(5).index],
        )
    elif mode_delta == pd.Timedelta(hours=1):
        check.warn(mode_delta=str(mode_delta), pct_hourly=pct_hourly)
    else:
        check.fail(mode_delta=str(mode_delta), pct_hourly=pct_hourly)
    checks.append(check)

    # --- 12. Missing time intervals ---------------------------------------------------
    check = Check("missing_time_intervals", "Missing time intervals")
    expected = pd.date_range(start=ts_full.min(), end=ts_full.max(), freq=FREQUENCY)
    actual = set(ts_full)
    missing_idx = [t for t in expected if t not in actual]
    gaps = len(missing_idx)
    gap_pct = round(gaps / len(expected) * 100, 4)
    if gaps == 0:
        check.pass_(expected_intervals=len(expected), missing_intervals=0)
    elif gap_pct <= 5.0:
        check.warn(
            expected_intervals=len(expected),
            missing_intervals=gaps,
            missing_pct=gap_pct,
            first_missing=[str(t) for t in missing_idx[:10]],
        )
    else:
        check.fail(
            expected_intervals=len(expected),
            missing_intervals=gaps,
            missing_pct=gap_pct,
            first_missing=[str(t) for t in missing_idx[:10]],
        )
    checks.append(check)

    # --- 13. Min / max consumption ------------------------------------------------------
    check = Check("min_max_consumption", "Min/max consumption")
    check.pass_(
        min=round(float(target.min()), 2),
        max=round(float(target.max()), 2),
        at_min=[str(i) for i in target[target == target.min()].index[:5]],
        at_max=[str(i) for i in target[target == target.max()].index[:5]],
    )
    checks.append(check)

    # --- 14. Mean / median consumption ----------------------------------------------------
    check = Check("mean_median_consumption", "Mean/median consumption")
    check.pass_(
        mean=round(float(target.mean()), 2),
        median=round(float(target.median()), 2),
        std=round(float(target.std()), 2),
    )
    checks.append(check)

    # --- 15. Outlier statistics --------------------------------------------------------------
    check = Check("outlier_statistics", "Outlier statistics (IQR / z-score)")
    q1, q3 = target.quantile(0.25), target.quantile(0.75)
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    iqr_outliers = int(((target < lower) | (target > upper)).sum())
    zscore = (target - target.mean()) / target.std()
    z_outliers = int((zscore.abs() > 3).sum())
    if iqr_outliers == 0 and z_outliers == 0:
        check.pass_(iqr_outliers=0, zscore_outliers=0)
    else:
        check.warn(
            method="IQR fences (1.5x) and z-score > 3",
            iqr_outliers=iqr_outliers,
            iqr_outlier_pct=round(iqr_outliers / n_clean * 100, 4),
            zscore_outliers=z_outliers,
            zscore_outlier_pct=round(z_outliers / n_clean * 100, 4),
            iqr_fences=[round(lower, 2), round(upper, 2)],
        )
    checks.append(check)

    # --- Sufficient records ----------------------------------------------------------------------
    check = Check("sufficient_records", "Sufficient number of records")
    if n_clean >= MIN_RECORDS:
        check.pass_(records=n_clean, min_required=MIN_RECORDS)
    else:
        check.fail(records=n_clean, min_required=MIN_RECORDS)
    checks.append(check)

    # --- Final status -----------------------------------------------------------------------------
    final = "PASS"
    for c in checks:
        if c.status == "FAIL":
            final = "FAIL"
            break
        if c.status == "WARN":
            final = "WARN"
    log.info("Final validation status: %s", final)

    # --- Persist cleaned artifact ----------------------------------------------------------------
    clean.to_parquet(CLEANED_DATA, index=True)
    log.info("Cleaned hourly series written to %s", CLEANED_DATA)

    # --- Persist report ---------------------------------------------------------------------------
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": {
            "kaggle_slug": KAGGLE_DATASET,
            "raw_file": str(raw_file),
            "raw_shape": [n_rows, n_cols],
        },
        "units": {
            "consumption_unit": CONSUMPTION_UNIT,
            "energy_unit": ENERGY_UNIT,
            "kwh_per_mwh": KWH_PER_MWH,
            "scope": DATA_SCOPE,
            "description": (
                f"Hourly {CONSUMPTION_UNIT} average load over the "
                f"{DATA_SCOPE} (whole-region/ENTSO-E Madrid area), not "
                "household consumption. Summing the hourly values yields "
                f"energy in {ENERGY_UNIT}."
            ),
        },
        "shape": {"rows_clean": int(n_clean), "columns_raw": int(n_cols)},
        "date_range": {
            "start": str(ts_full.min()),
            "end": str(ts_full.max()),
            "span_days": round(span_days, 2),
        },
        "sampling_frequency": {"mode_delta": str(mode_delta), "pct_hourly": pct_hourly},
        "missing": {
            "total_cells": int(df.isna().sum().sum()),
            "target_missing": int(df[TARGET_COLUMN].isna().sum()),
        },
        "duplicates": {
            "rows": dup_rows,
            "timestamps": dup_ts,
        },
        "statistics": {
            "min": round(float(target.min()), 2),
            "max": round(float(target.max()), 2),
            "mean": round(float(target.mean()), 2),
            "median": round(float(target.median()), 2),
            "std": round(float(target.std()), 2),
            "negative_count": neg_count,
            "outliers": {
                "iqr": iqr_outliers,
                "zscore": z_outliers,
            },
        },
        "checks": [c.to_dict() for c in checks],
        "final_status": final,
        "artifacts": {
            "quality_report": str(QUALITY_REPORT),
            "cleaned_data": str(CLEANED_DATA),
        },
    }
    QUALITY_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("Quality report written to %s", QUALITY_REPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
