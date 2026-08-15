"""User upload service (Phase 11).

Accepts a CSV / XLSX file, detects the timestamp + consumption columns, builds
a cleaned datetime-indexed series, runs a structured validation report, infers
frequency and scope, and persists the uploaded dataset behind a generated
``dataset_id`` under ``UPLOAD_DIR`` (gitignored, isolated from the original
project series — forecasts operate only on this uploaded data).

Storage layout (``UPLOAD_DIR``):
  * ``{dataset_id}.parquet`` -> cleaned ``consumption`` series (datetime index)
  * ``{dataset_id}.json``    -> metadata + preview + validation summary
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .. import config as api_config  # noqa: E402 (bootstraps ml/scripts sys.path)

import config as ml_config  # noqa: E402

from ..errors import BadRequestError, NotFoundError  # noqa: E402

log = logging.getLogger("api.uploads")

# Common timestamp / consumption column aliases (case-insensitive, matched on
# the normalized column name).
TIMESTAMP_ALIASES = ["timestamp", "datetime", "date", "time", "data", "time_stamp"]
CONSUMPTION_ALIASES = [
    "consumption",
    "load",
    "demand",
    "energy",
    "power",
    "electricity_consumption",
    "electricity",
    "total_load_actual",
    "total load actual",
    "usage",
    "kwh",
    "value",
]
_SCOPE_MW_CHECK = re.compile(r"mwh?$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------------
def _normalise(name: str) -> str:
    return str(name).strip().lower().replace("_", " ").replace("-", " ")


def detect_timestamp_column(frame: pd.DataFrame) -> str | None:
    """Pick the timestamp column: exact alias match first, else a parseable one."""
    columns = {c: _normalise(c) for c in frame.columns}
    for candidate in TIMESTAMP_ALIASES:
        for col, norm in columns.items():
            if norm == candidate:
                return col
    # Fallback: first column whose values all coerce to datetimes.
    for col in frame.columns:
        try:
            parsed = pd.to_datetime(frame[col].astype(str), format="mixed")
            if parsed.notna().mean() >= 0.9:
                return col
        except (ValueError, TypeError, OverflowError):
            continue
    return None


def detect_consumption_column(frame: pd.DataFrame) -> str | None:
    """Pick the consumption column: alias match first, else a plausible numeric one."""
    columns = {c: _normalise(c) for c in frame.columns}
    for candidate in CONSUMPTION_ALIASES:
        for col, norm in columns.items():
            if norm == candidate:
                return col
    numeric = [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]
    if not numeric:
        return None
    # Prefer the numeric column with the widest positive range (most likely the
    # consumption series rather than a small id/counter column).
    best, best_range = None, -1.0
    for col in numeric:
        values = pd.to_numeric(frame[col], errors="coerce").dropna()
        if len(values) < 2:
            continue
        if values.min() < 0:
            continue
        span = float(values.max() - values.min())
        if span > best_range:
            best, best_range = col, span
    return best


# ---------------------------------------------------------------------------
# Cleansing
# ---------------------------------------------------------------------------
def parse_timestamps(series: pd.Series) -> pd.Series:
    """Parse timestamps to tz-naive datetimes, tolerating mixed formats/offsets."""
    parsed = pd.to_datetime(series.astype(str), format="mixed", errors="coerce")
    if parsed.dt.tz is not None:
        parsed = parsed.dt.tz_localize(None)
    return parsed


def build_clean_series(
    frame: pd.DataFrame, ts_col: str, cons_col: str
) -> tuple[pd.Series, dict[str, int]]:
    """Validate + clean the two selected columns into a sorted consumption series.

    Returns (series, counts) where counts reports removed/invalid rows so the
    validation report can surface them. Negative consumption values are treated
    as invalid (removed), matching the Phase 1 pipeline's semantics.
    """
    ts = parse_timestamps(frame[ts_col])
    cons = pd.to_numeric(frame[cons_col], errors="coerce")

    counts: dict[str, int] = {
        "rows_total": int(len(frame)),
        "unparseable_timestamps": int(ts.isna().sum()),
        "non_numeric_consumption": int(cons.isna().sum()),
        "negative": 0,
    }

    cleaned = pd.DataFrame({"timestamp": ts, "consumption": cons}).dropna(
        subset=["timestamp", "consumption"]
    )
    negative_mask = cleaned["consumption"] < 0
    counts["negative"] = int(negative_mask.sum())
    cleaned = cleaned[~negative_mask]

    cleaned = cleaned.sort_values("timestamp")
    duplicates = int(cleaned["timestamp"].duplicated().sum())
    counts["duplicate_timestamps"] = duplicates
    cleaned = cleaned.drop_duplicates("timestamp").set_index("timestamp")
    cleaned.index.name = "timestamp"

    if cleaned.empty:
        raise BadRequestError(
            "no usable consumption rows after cleanup (check the timestamp and "
            "consumption columns in your file)."
        )
    return cleaned["consumption"], counts


# ---------------------------------------------------------------------------
# Frequency / scope inference
# ---------------------------------------------------------------------------
def infer_frequency(series: pd.Series) -> dict:
    """Infer the sampling frequency of a sorted datetime-indexed series."""
    if len(series) < 2:
        return {"label": "other", "stats": {}, "note": "too few rows to infer"}
    deltas = series.index.to_series().diff().dropna()
    stats = deltas.describe().to_dict()
    mode_delta = deltas.mode().iloc[0]

    inferred = pd.infer_freq(series.index[:10])
    label = "other"
    if inferred == "H":
        label = "hourly"
    elif inferred and inferred.startswith("min"):
        label = inferred.replace("min", "min") + "ly"
        label = "minutely" if inferred == "min" else f"{inferred.rstrip('min')}min"
    elif inferred == "D":
        label = "daily"
    elif inferred == "W" or (inferred and inferred.startswith("W")):
        label = "weekly"
    elif inferred in ("MS", "M", "ME"):
        label = "monthly"
    else:
        seconds = mode_delta.total_seconds()
        if seconds == 3600:
            label = "hourly"
        elif seconds == 1800:
            label = "30min"
        elif seconds in (900,):
            label = "15min"
        elif seconds == 86400:
            label = "daily"
        elif seconds == 604800:
            label = "weekly"
        elif 28 * 86400 <= seconds <= 31 * 86400:
            label = "monthly"
    sec_series = deltas.dt.total_seconds()
    return {
        "label": label,
        "inferred_alias": inferred,
        "mode_delta": str(mode_delta),
        "stats": {k: round(float(v), 2) for k, v in sec_series.describe().to_dict().items()},
    }


_SCOPE_NAME_KWH = re.compile(r"kwh|watts?|kw\b", re.IGNORECASE)
_SCOPE_NAME_MW = re.compile(r"(^|[^k])mwh?|mw$|gigawatts?", re.IGNORECASE)


def infer_scope(series: pd.Series, column_name: str, frequency_label: str) -> dict:
    """Heuristically detect household vs regional-grid scope from column name +
    magnitude. Returns an explicitly-labeled guess; users can override when it
    is unclear (``need_selection``).
    """
    column_hint = _normalise(column_name)

    if _SCOPE_NAME_KWH.search(column_hint):
        return _scope_result("household", "kWh", "column_name", False)
    if _SCOPE_NAME_MW.search(column_hint):
        unit = "MWh" if "mwh" in column_hint else "MW"
        return _scope_result("regional_grid", unit, "column_name", False)

    median = float(series.median()) if len(series) else 0.0
    if frequency_label in ("hourly", "30min", "15min", "minutely"):
        if median < 1000:
            return _scope_result("household", "kWh", "magnitude", False)
        return _scope_result("regional_grid", "MW", "magnitude", False)
    if frequency_label in ("daily", "weekly"):
        if median < 2000:
            return _scope_result("household", "kWh", "magnitude", False)
        return _scope_result("regional_grid", "MWh", "magnitude", False)
    if median < 2000:
        return _scope_result("household", "kWh", "magnitude", True)
    return _scope_result("regional_grid", "MWh", "magnitude", True)


def _scope_result(scope: str, unit: str, source: str, need_selection: bool) -> dict:
    return {
        "scope": scope,
        "unit": unit,
        "detected_by": source,
        "need_selection": need_selection,
        "note": (
            "heuristic scope/unit guess; overridable on forecast generation."
            if need_selection
            else f"detected via {source} heuristic"
        ),
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_upload(frame: pd.DataFrame, series: pd.Series, ts_col: str | None,
                    cons_col: str | None, frequency: dict) -> dict:
    """Run the structured validation checks (mirrors the Phase 1 quality report).

    Returns a report of PASS/WARN/FAIL checks + a final status (valid/warn/invalid).
    """
    checks: list[dict] = []

    def check(check_id: str, name: str, status: str, **details) -> None:
        checks.append({"id": check_id, "name": name, "status": status, "details": details})

    # 1. Columns present
    if ts_col is None or cons_col is None:
        check("columns", "Timestamp + consumption columns",
              "FAIL", timestamp_column=ts_col, consumption_column=cons_col)
    elif ts_col == cons_col:
        check("columns", "Timestamp + consumption columns",
              "FAIL", detail="timestamp and consumption selected the same column")
    else:
        check("columns", "Timestamp + consumption columns", "PASS",
              timestamp_column=ts_col, consumption_column=cons_col)

    # 2. Timestamps parse
    raw_ts = parse_timestamps(frame[ts_col]) if ts_col else pd.Series(dtype="datetime64[ns]")
    unparsed = int(raw_ts.isna().sum())
    if unparsed == 0:
        check("timestamp_parsing", "Timestamp parsing", "PASS", unparsed=0)
    else:
        check("timestamp_parsing", "Timestamp parsing", "FAIL",
              unparsed=unparsed, pct=round(unparsed / len(frame) * 100, 4))

    # 3. Duplicate timestamps
    dup = int(raw_ts.dropna().duplicated().sum())
    if dup == 0:
        check("duplicate_timestamps", "Duplicate timestamps", "PASS", count=0)
    else:
        check("duplicate_timestamps", "Duplicate timestamps", "WARN",
              count=dup, pct=round(dup / len(frame) * 100, 4),
              note="duplicate rows were removed during cleanup")

    # 4. Missing values in the consumption column
    if cons_col:
        cons = pd.to_numeric(frame[cons_col], errors="coerce")
        missing = int(cons.isna().sum())
        if missing == 0:
            check("missing_values", "Missing values", "PASS", count=0)
        else:
            pct = round(missing / len(frame) * 100, 4)
            status = "WARN" if pct <= 5.0 else "FAIL"
            check("missing_values", "Missing values", status, count=missing, pct=pct)

    # 5. Negative values (after cleanup the series has none)
    neg = int((series < 0).sum())
    if neg == 0:
        check("negative_values", "Negative consumption", "PASS", count=0)
    else:
        check("negative_values", "Negative consumption", "FAIL", count=neg)

    # 6. Ordering (sorted)
    raw_sorted = bool(raw_ts.dropna().is_monotonic_increasing) if len(raw_ts) else True
    if raw_sorted:
        check("timestamp_ordering", "Timestamp ordering", "PASS")
    else:
        check("timestamp_ordering", "Timestamp ordering", "WARN",
              note="file not sorted; cleaned series was sorted")

    # 7. Frequency
    freq_ok = frequency["label"] in ("hourly", "30min", "15min", "daily", "weekly", "monthly")
    check("frequency", "Sampling frequency", "PASS" if freq_ok else "WARN",
          label=frequency["label"], mode_delta=frequency["mode_delta"])

    # 8. Gaps (missing intervals at the inferred frequency over the full range)
    freq = _pandas_freq(frequency["label"])
    expected = pd.date_range(start=series.index.min(), end=series.index.max(), freq=freq) if freq else series.index
    missing_intervals = int(len(expected) - len(series))
    gap_pct = round(missing_intervals / len(expected) * 100, 4) if len(expected) else 0.0
    if missing_intervals == 0:
        check("gaps", "Missing time intervals", "PASS", missing=0)
    elif gap_pct <= 5.0:
        check("gaps", "Missing time intervals", "WARN", missing=missing_intervals, pct=gap_pct)
    else:
        check("gaps", "Missing time intervals", "FAIL", missing=missing_intervals, pct=gap_pct)

    # 9. Basic statistics
    check("statistics", "Basic statistics", "PASS",
          rows=int(len(series)),
          min=round(float(series.min()), 3),
          max=round(float(series.max()), 3),
          mean=round(float(series.mean()), 3),
          median=round(float(series.median()), 3),
          std=round(float(series.std()), 3) if len(series) > 1 else 0.0)

    # 10. History sufficiency (for forecast reliability warnings)
    span_days = (series.index.max() - series.index.min()).total_seconds() / 86400.0
    if span_days >= api_config.MEDIUM_TERM_MIN_HISTORY_DAYS:
        check("history_sufficiency", "Historical depth", "PASS", span_days=round(span_days, 2))
    else:
        check("history_sufficiency", "Historical depth", "WARN",
              span_days=round(span_days, 2),
              note=("short history limits forecast reliability; at least "
                    f"{api_config.MEDIUM_TERM_MIN_HISTORY_DAYS} days recommended"))

    final = "PASS"
    for c in checks:
        if c["status"] == "FAIL":
            final = "FAIL"
            break
        if c["status"] == "WARN":
            final = "WARN"
    if final == "PASS":
        validation_status = "valid"
    elif final == "WARN":
        validation_status = "warn"
    else:
        validation_status = "invalid"
    return {
        "status": validation_status,
        "final_status": final,
        "checks": checks,
        "missing_intervals": missing_intervals,
        "gap_pct": gap_pct,
    }


def _pandas_freq(label: str) -> str | None:
    if label == "hourly":
        return "h"
    if label == "30min":
        return "30min"
    if label == "15min":
        return "15min"
    if label == "daily":
        return "D"
    if label == "weekly":
        return "W"
    if label == "monthly":
        return "MS"
    return None


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def _dataset_series_path(dataset_id: str) -> Path:
    return api_config.UPLOAD_DIR / f"{dataset_id}.parquet"


def _dataset_meta_path(dataset_id: str) -> Path:
    return api_config.UPLOAD_DIR / f"{dataset_id}.json"


def _new_dataset_id() -> str:
    return f"ds_{uuid.uuid4().hex[:16]}"


def _frame_from_file(filename: str, content: bytes) -> pd.DataFrame:
    """Parse uploaded bytes into a DataFrame (CSV or XLSX via openpyxl)."""
    ext = Path(filename).suffix.lower()
    if ext == ".xlsx":
        try:
            import io

            return pd.read_excel(io.BytesIO(content), engine="openpyxl")
        except Exception as exc:  # noqa: BLE001 - surface a clear user message
            raise BadRequestError(f"could not read Excel file: {exc}") from exc
    # .csv — tolerate several delimiters/quoted fields without user edits.
    try:
        return pd.read_csv(__import__("io").BytesIO(content))
    except Exception as exc:  # noqa: BLE001
        raise BadRequestError(f"could not read CSV file: {exc}") from exc


def read_uploaded_frame(filename: str, content: bytes) -> tuple[pd.DataFrame, str]:
    """Validate extension/size and parse the upload into a DataFrame."""
    if not filename or not Path(filename).suffix:
        raise BadRequestError("uploaded file must have a .csv or .xlsx extension")
    ext = Path(filename).suffix.lower()
    if ext not in api_config.ALLOWED_UPLOAD_EXTENSIONS:
        raise BadRequestError(
            f"unsupported file type '{ext}'. Allowed: {api_config.ALLOWED_UPLOAD_EXTENSIONS}"
        )
    if len(content) <= 0:
        raise BadRequestError("uploaded file is empty")
    if len(content) > api_config.MAX_UPLOAD_SIZE:
        raise BadRequestError(
            f"upload too large ({len(content) / 1e6:.1f} MB). "
            f"Max: {api_config.MAX_UPLOAD_SIZE_MB} MB"
        )
    frame = _frame_from_file(filename, content)
    if frame is None or frame.empty:
        raise BadRequestError("uploaded file contains no data rows")
    return frame, ext


def process_upload(filename: str, content: bytes) -> dict:
    """Full upload pipeline: parse -> detect -> clean -> validate -> persist.

    Returns the upload metadata + validation report (see the POST /upload doc).
    """
    api_config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_stale()

    frame, _ext = read_uploaded_frame(filename, content)

    ts_col = detect_timestamp_column(frame)
    cons_col = detect_consumption_column(frame)

    if ts_col is None and cons_col is None:
        raise BadRequestError(
            f"could not detect a timestamp column or a consumption column in "
            f"{filename}. Provide a time column (timestamp/datetime/date/time) "
            "and a consumption column (consumption/load/demand/energy/kwh)."
        )
    if ts_col is None:
        raise BadRequestError(
            f"missing timestamp column in {filename}. Expected one of: "
            f"{TIMESTAMP_ALIASES}"
        )
    if cons_col is None or cons_col == ts_col:
        raise BadRequestError(
            f"missing consumption column in {filename}. Expected one of: "
            f"{CONSUMPTION_ALIASES}"
        )

    series, counts = build_clean_series(frame, ts_col, cons_col)
    frequency = infer_frequency(series)
    validation = validate_upload(frame, series, ts_col, cons_col, frequency)
    scope = infer_scope(series, str(cons_col), frequency["label"])

    dataset_id = _new_dataset_id()
    series_df = series.to_frame()
    series_df.to_parquet(_dataset_series_path(dataset_id), index=True)

    metadata = {
        "dataset_id": dataset_id,
        "filename": filename,
        "rows": int(len(series)),
        "rows_total": int(counts["rows_total"]),
        "removed_rows": {
            key: counts.get(key, 0)
            for key in ("unparseable_timestamps", "non_numeric_consumption", "negative", "duplicate_timestamps")
        },
        "start_date": str(series.index.min()),
        "end_date": str(series.index.max()),
        "frequency": frequency,
        "timestamp_column": ts_col,
        "consumption_column": cons_col,
        "unit": scope["unit"],
        "energy_unit": _energy_unit_for(scope["scope"], scope["unit"], frequency["label"]),
        "scope": scope,
        "validation": {
            "status": validation["status"],
            "final_status": validation["final_status"],
            "checks": validation["checks"],
        },
        "statistics": {
            "min": round(float(series.min()), 3),
            "max": round(float(series.max()), 3),
            "mean": round(float(series.mean()), 3),
            "median": round(float(series.median()), 3),
            "std": round(float(series.std()), 3) if len(series) > 1 else 0.0,
        },
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _dataset_meta_path(dataset_id).write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    log.info("dataset %s stored (rows=%d file=%s)", dataset_id, len(series), filename)

    return upload_summary(metadata)


def _energy_unit_for(scope: str, unit: str, frequency_label: str) -> str:
    if scope == "regional_grid":
        return "MWh"
    if scope == "household":
        return "kWh"
    return unit or "kWh"


def upload_summary(metadata: dict) -> dict:
    """Public upload response shaped for the API + frontend."""
    validation = metadata["validation"]
    warnings = [
        {"id": c["id"], "message": _warning_message(c)}
        for c in validation["checks"]
        if c["status"] in ("WARN", "FAIL")
    ]
    return {
        "dataset_id": metadata["dataset_id"],
        "filename": metadata["filename"],
        "rows": metadata["rows"],
        "rows_total": metadata["rows_total"],
        "removed_rows": metadata["removed_rows"],
        "start_date": metadata["start_date"],
        "end_date": metadata["end_date"],
        "frequency": metadata["frequency"]["label"],
        "timestamp_column": metadata["timestamp_column"],
        "consumption_column": metadata["consumption_column"],
        "unit": metadata["unit"],
        "energy_unit": metadata["energy_unit"],
        "scope": metadata["scope"],
        "validation_status": validation["status"],
        "warnings": warnings,
        "statistics": metadata["statistics"],
        "created_at": metadata["created_at"],
    }


def _warning_message(check: dict) -> str:
    cid, details = check["id"], check["details"]
    if cid == "missing_values":
        return f"Missing consumption values: {details.get('count')} rows ({details.get('pct')}%)."
    if cid == "duplicate_timestamps":
        return f"Duplicate timestamps found ({details.get('count')}) and removed."
    if cid == "timestamp_ordering":
        return "Timestamps were not sorted; the upload was re-sorted chronologically."
    if cid == "history_sufficiency":
        return f"Only {details.get('span_days')} days of history — at least 30 days is recommended."
    if cid == "frequency":
        return f"Unusual sampling frequency '{details.get('label')}' detected."
    if cid == "gaps":
        return f"Missing time intervals: {details.get('missing')} ({details.get('pct')}%)."
    if cid == "negative_values":
        return "Negative consumption values were found and removed."
    return f"{check['name']}: {check['status']}"


# ---------------------------------------------------------------------------
# Retrieval + cleanup
# ---------------------------------------------------------------------------
@lru_cache(maxsize=64)
def get_series(dataset_id: str) -> pd.Series:
    """Load a stored uploaded series (cached per dataset_id)."""
    path = _dataset_series_path(dataset_id)
    if not path.exists():
        raise NotFoundError(f"unknown dataset '{dataset_id}'. Upload it first via POST /forecast/upload.")
    df = pd.read_parquet(path)
    series = pd.Series(df.iloc[:, 0], index=pd.to_datetime(df.index), name=df.columns[0])
    return series.sort_index()


def get_metadata(dataset_id: str) -> dict:
    path = _dataset_meta_path(dataset_id)
    if not path.exists():
        raise NotFoundError(f"unknown dataset '{dataset_id}'. Upload it first via POST /forecast/upload.")
    return json.loads(path.read_text(encoding="utf-8"))


def dataset_report(dataset_id: str, preview_limit: int = 10) -> dict:
    """Dataset metadata + a small preview table for the confirmation screen."""
    metadata = get_metadata(dataset_id)
    series = get_series(dataset_id)
    return {
        **metadata,
        "preview": [
            {"timestamp": str(ts), "consumption": round(float(v), 3)}
            for ts, v in series.head(preview_limit).items()
        ],
    }


def recent_datasets(limit: int = 5) -> list[dict]:
    """Summaries of the most recently uploaded datasets (mtime-sorted, newest first).

    Used by the household dashboard / analytics / agent to find the active
    dataset without a stored pointer (uploads are ephemeral, single-user).
    """
    if not api_config.UPLOAD_DIR.is_dir():
        return []
    metas = []
    for path in api_config.UPLOAD_DIR.glob("ds_*.json"):
        try:
            metas.append((path.stat().st_mtime, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            continue
    metas.sort(key=lambda item: item[0], reverse=True)
    return [upload_summary(meta) for _, meta in metas[: max(1, int(limit))]]


def cleanup_stale() -> int:
    """Remove uploaded datasets older than UPLOAD_TTL_S and evict expired caches."""
    if not api_config.UPLOAD_DIR.is_dir():
        return 0
    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - api_config.UPLOAD_TTL_S
    removed = 0
    for path in api_config.UPLOAD_DIR.glob("ds_*.parquet"):
        if path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            _dataset_meta_path(path.stem).unlink(missing_ok=True)
            get_series.cache_clear()
            removed += 1
    return removed


def clear_uploads() -> None:
    """Remove every uploaded dataset (startup hygiene for the ephemeral store)."""
    if not api_config.UPLOAD_DIR.is_dir():
        return
    for path in api_config.UPLOAD_DIR.glob("ds_*"):
        path.unlink(missing_ok=True)
    get_series.cache_clear()


# Re-export for convenience
def candidate_aliases() -> dict[str, Any]:
    return {"timestamp": TIMESTAMP_ALIASES, "consumption": CONSUMPTION_ALIASES}