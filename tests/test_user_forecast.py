"""Automated tests for Phase 11 — user upload + flexible forecasting.

Covers CSV/XLSX upload, column detection, validation reports, horizon
strategy (short/medium/long term), L/M/H classification, peak analysis,
recommendations, the household bill (household scope only), regional-scope
separation, CSV exports and error handling. All forecasts run on synthetic
uploaded data via FastAPI's TestClient; no external network requests.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.main import app  # noqa: E402
from backend.app.services import upload_service  # noqa: E402

API = "/api/v1"
client = TestClient(app)
rng = np.random.default_rng(7)


# ---------------------------------------------------------------------------
# Synthetic data builders
# ---------------------------------------------------------------------------
def hourly_household_csv() -> bytes:
    """120 days of hourly kWh consumption (mean ~400) — household scope."""
    idx = pd.date_range("2024-01-01", periods=120 * 24, freq="h")
    base = 400 + 45 * np.sin(2 * np.pi * idx.hour / 24)
    weekend = np.where((idx.dayofweek >= 5), -35, 25)
    trend = np.linspace(0, 30, len(idx))
    vals = np.clip(base + weekend + trend + rng.normal(0, 8, len(idx)), 120, 700)
    df = pd.DataFrame({"timestamp": idx.strftime("%Y-%m-%d %H:%M:%S"),
                       "consumption": vals.round(3)})
    return df.to_csv(index=False).encode("utf-8")


def daily_household_csv() -> bytes:
    """365 days of daily kWh (seasonal yearly cycle) — household scope."""
    idx = pd.date_range("2024-01-01", periods=365, freq="D")
    vals = 9000 + 1500 * np.sin(2 * np.pi * idx.dayofyear / 365) + rng.normal(0, 150, len(idx))
    df = pd.DataFrame({"timestamp": idx.strftime("%Y-%m-%d"),
                       "consumption_kwh": vals.round(2)})
    return df.to_csv(index=False).encode("utf-8")


def regional_hourly_csv() -> bytes:
    """60 days of hourly grid demand (~30 GW) — regional scope."""
    idx = pd.date_range("2024-06-01", periods=60 * 24, freq="h")
    vals = 30000 + 4500 * np.sin(2 * np.pi * idx.hour / 24) + rng.normal(0, 1200, len(idx))
    df = pd.DataFrame({"timestamp": idx.strftime("%Y-%m-%d %H:%M:%S"),
                       "total_load_actual": vals.round(2)})
    return df.to_csv(index=False).encode("utf-8")


def high_consumption_1year_daily_csv() -> bytes:
    """365 days of DAILY kWh (mean ~9000/day) with a strong yearly cycle.

    Mirrors the real-world ''SmartGridAI_household_HIGH_consumption_1year.csv''
    shape: objectively high consumption. The expected classification is
    derived from the forecast vs the uploaded percentiles — never from the
    filename — so the test asserts the diagnostic stats, not a hard-coded label.
    """
    idx = pd.date_range("2024-01-01", periods=365, freq="D")
    vals = 9000 + 1500 * np.sin(2 * np.pi * idx.dayofyear / 365) + rng.normal(0, 150, len(idx))
    df = pd.DataFrame({"timestamp": idx.strftime("%Y-%m-%d"),
                       "consumption_kwh": vals.round(2)})
    return df.to_csv(index=False).encode("utf-8")


def high_peak_30min_csv() -> bytes:
    """90 days of 30-minute household kWh: low baseline + sharp peaks.

    Mirrors ''SmartGridAI_household_HIGH_PEAK_test.csv'': rare high periods that
    must still be detected against the household's own historical p90.
    """
    idx = pd.date_range("2024-01-01", periods=90 * 48, freq="30min")
    base = np.where(idx.hour.isin(range(17, 22)), 8.0, 1.5)
    peaks = rng.random(len(idx)) < 0.02
    vals = np.where(peaks, 60.0 + rng.normal(0, 5, len(idx)), base + rng.normal(0, 0.4, len(idx)))
    vals = np.maximum(0.1, vals)
    df = pd.DataFrame({"timestamp": idx.strftime("%Y-%m-%d %H:%M:%S"),
                       "consumption": vals.round(3)})
    return df.to_csv(index=False).encode("utf-8")


def _upload(content: bytes, filename: str = "household_hourly.csv") -> dict:
    r = client.post(
        f"{API}/forecast/upload",
        files={"file": (filename, content, "text/csv")},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def datasets():
    upload_service.clear_uploads()
    return {
        "household": _upload(hourly_household_csv(), "household_hourly.csv"),
        "household_daily": _upload(daily_household_csv(), "household_daily.csv"),
        "regional": _upload(regional_hourly_csv(), "regional_hourly.csv"),
        "high_consumption": _upload(high_consumption_1year_daily_csv(),
                                    "SmartGridAI_household_HIGH_consumption_1year.csv"),
        "high_peak": _upload(high_peak_30min_csv(),
                             "SmartGridAI_household_HIGH_PEAK_test.csv"),
    }


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
def test_upload_csv_household_valid(datasets):
    body = datasets["household"]
    assert body["dataset_id"].startswith("ds_")
    assert body["filename"] == "household_hourly.csv"
    assert body["frequency"] == "hourly"
    assert body["rows"] == 120 * 24
    assert body["validation_status"] == "valid"
    assert body["scope"]["scope"] == "household"
    assert body["scope"]["unit"] == "kWh"
    assert body["unit"] == "kWh"
    assert body["energy_unit"] == "kWh"
    assert body["timestamp_column"] == "timestamp"
    assert body["consumption_column"] == "consumption"


def test_upload_xlsx_valid():
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=48, freq="h").strftime("%Y-%m-%d %H:%M:%S"),
        "kWh": (rng.normal(400, 40, 48).round(3)),
    })
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    body = _upload(buf.getvalue(), "household.xlsx")
    assert body["frequency"] == "hourly"
    assert body["scope"]["scope"] == "household"
    assert body["consumption_column"] == "kWh"
    assert body["rows"] == 48


def test_upload_rejects_bad_extension():
    r = client.post(f"{API}/forecast/upload",
                    files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400
    assert "unsupported file type" in r.json()["error"]["message"]


def test_upload_rejects_extensionless():
    r = client.post(f"{API}/forecast/upload",
                    files={"file": ("noext", b"hello", "text/plain")})
    assert r.status_code == 400


def test_upload_rejects_missing_columns():
    df = pd.DataFrame({"id": range(10)})
    r = client.post(f"{API}/forecast/upload",
                    files={"file": ("bad.csv", df.to_csv(index=False).encode(), "text/csv")})
    assert r.status_code == 400
    assert "timestamp" in r.json()["error"]["message"]


def test_upload_rejects_header_only():
    r = client.post(f"{API}/forecast/upload",
                    files={"file": ("empty.csv", b"timestamp,consumption\n", "text/csv")})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Dataset report
# ---------------------------------------------------------------------------
def test_dataset_report_metadata_and_preview(datasets):
    body = datasets["household"]
    r = client.get(f"{API}/forecast/datasets/{body['dataset_id']}")
    assert r.status_code == 200
    data = r.json()
    assert data["dataset_id"] == body["dataset_id"]
    assert len(data["preview"]) == 10
    assert data["preview"][0]["timestamp"].startswith("2024-01-01")
    assert data["statistics"]["mean"] > 0


def test_dataset_report_unknown_404():
    r = client.get(f"{API}/forecast/datasets/ds_doesnotexist")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Horizon strategy
# ---------------------------------------------------------------------------
def test_generate_short_term_1day_ml(datasets):
    ds = datasets["household"]["dataset_id"]
    r = client.post(f"{API}/forecast/generate",
                    json={"dataset_id": ds, "horizon_value": 1, "horizon_unit": "days"})
    assert r.status_code == 200
    body = r.json()
    assert body["forecast_type"] == "short_term"
    assert body["display_granularity"] == "hourly"
    assert body["horizon"]["days"] == 1
    assert len(body["points"]) == 24
    assert body["intervals_available"] is True
    assert body["points"][0]["lower_bound"] is not None
    assert body["points"][0]["upper_bound"] is not None


def test_generate_short_term_7days(datasets):
    ds = datasets["household"]["dataset_id"]
    r = client.post(f"{API}/forecast/generate",
                    json={"dataset_id": ds, "horizon_value": 7, "horizon_unit": "days"})
    assert r.status_code == 200
    body = r.json()
    assert body["forecast_type"] == "short_term"
    assert len(body["points"]) == 7 * 24


def test_generate_short_term_non_hourly_uses_seasonal(datasets):
    ds = datasets["household_daily"]["dataset_id"]
    r = client.post(f"{API}/forecast/generate",
                    json={"dataset_id": ds, "horizon_value": 1, "horizon_unit": "days"})
    assert r.status_code == 200
    body = r.json()
    assert body["forecast_type"] == "short_term"
    assert body["display_granularity"] == "daily"
    assert len(body["points"]) == 1


def test_generate_medium_term_30days_daily(datasets):
    ds = datasets["household"]["dataset_id"]
    r = client.post(f"{API}/forecast/generate",
                    json={"dataset_id": ds, "horizon_value": 30, "horizon_unit": "days"})
    assert r.status_code == 200
    body = r.json()
    assert body["forecast_type"] == "medium_term"
    assert body["display_granularity"] == "daily"
    assert body["summary"]["periods"] == 30
    assert len(body["points"]) == 30


def test_generate_long_term_1year_monthly(datasets):
    ds = datasets["household"]["dataset_id"]
    r = client.post(f"{API}/forecast/generate",
                    json={"dataset_id": ds, "horizon_value": 12, "horizon_unit": "months"})
    assert r.status_code == 200
    body = r.json()
    assert body["forecast_type"] == "long_term"
    assert body["display_granularity"] == "monthly"
    assert body["horizon"]["days"] == 360
    assert 12 <= len(body["points"]) <= 14
    # Long-term weather is explicitly labelled, never fabricated as available.
    assert body["weather"]["status"] == "not_available"


def test_generate_long_term_2years(datasets):
    ds = datasets["household"]["dataset_id"]
    r = client.post(f"{API}/forecast/generate",
                    json={"dataset_id": ds, "horizon_value": 2, "horizon_unit": "years"})
    assert r.status_code == 200
    body = r.json()
    assert body["forecast_type"] == "long_term"
    assert body["horizon"]["days"] == 730
    assert len(body["points"]) >= 24


# ---------------------------------------------------------------------------
# Horizon validation
# ---------------------------------------------------------------------------
def test_generate_invalid_horizon_unit_rejected(datasets):
    ds = datasets["household"]["dataset_id"]
    r = client.post(f"{API}/forecast/generate",
                    json={"dataset_id": ds, "horizon_value": 1, "horizon_unit": "fortnights"})
    assert r.status_code == 422


def test_generate_horizon_exceeds_max_days(datasets):
    ds = datasets["household"]["dataset_id"]
    # 3 years = 1095 days > 730: passes the schema bound then rejected in resolve.
    r = client.post(f"{API}/forecast/generate",
                    json={"dataset_id": ds, "horizon_value": 3, "horizon_unit": "years"})
    assert r.status_code == 400
    assert "exceeds the maximum" in r.json()["error"]["message"]


def test_generate_unknown_dataset_404():
    r = client.post(f"{API}/forecast/generate",
                    json={"dataset_id": "ds_nope", "horizon_value": 1, "horizon_unit": "days"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Classification + peak + recommendations
# ---------------------------------------------------------------------------
def test_generate_classification_thresholds_and_counts(datasets):
    ds = datasets["household"]["dataset_id"]
    body = client.post(f"{API}/forecast/generate",
                       json={"dataset_id": ds, "horizon_value": 30, "horizon_unit": "days"}).json()
    cls = body["classification"]
    low, high = cls["thresholds"]["low"], cls["thresholds"]["high"]
    assert 0 < low < high
    counts = cls["counts"]
    assert counts["LOW"] + counts["MEDIUM"] + counts["HIGH"] == body["summary"]["periods"]
    pct_total = round(sum(cls["percentages"].values()), 1)
    assert 99.0 <= pct_total <= 101.0
    for p in body["points"]:
        assert p["classification"] in ("LOW", "MEDIUM", "HIGH")


def test_generate_peak_analysis(datasets):
    ds = datasets["household"]["dataset_id"]
    body = client.post(f"{API}/forecast/generate",
                       json={"dataset_id": ds, "horizon_value": 30, "horizon_unit": "days"}).json()
    peak = body["peak"]
    assert peak["value"] == body["summary"]["maximum"]
    assert peak["peak_to_average_ratio"] >= 1.0
    assert peak["peak_to_average_ratio"] == round(body["summary"]["maximum"] / body["summary"]["average"], 3)
    assert body["points"][0]["timestamp"] < body["points"][-1]["timestamp"]


def test_generate_recommendations_are_traceable(datasets):
    ds = datasets["household"]["dataset_id"]
    body = client.post(f"{API}/forecast/generate",
                       json={"dataset_id": ds, "horizon_value": 30, "horizon_unit": "days"}).json()
    recs = body["recommendations"]
    assert len(recs) >= 1
    for rec in recs:
        assert rec["id"]
        assert rec["message"]
        assert rec["basis"]


def test_generate_returns_historical_tail(datasets):
    ds = datasets["household"]["dataset_id"]
    body = client.post(f"{API}/forecast/generate",
                       json={"dataset_id": ds, "horizon_value": 7, "horizon_unit": "days"}).json()
    assert len(body["historical"]) > 0
    assert all("timestamp" in h and "value" in h for h in body["historical"])


# ---------------------------------------------------------------------------
# Explainable household-relative classification (FIX report items)
# ---------------------------------------------------------------------------
def _classify(ds: str, hv: int, hu: str = "days") -> dict:
    body = client.post(f"{API}/forecast/generate",
                       json={"dataset_id": ds, "horizon_value": hv, "horizon_unit": hu}).json()
    assert body["status"] in ("LOW", "MEDIUM", "HIGH")
    return body


def test_1_normal_household_has_full_diagnostics(datasets):
    body = _classify(datasets["household"]["dataset_id"], 30)
    cls = body["classification"]
    assert cls["historical_mean"] > 0
    assert cls["forecast_mean"] > 0
    assert cls["historical_90th_percentile"] > 0
    assert 0 <= cls["high_period_count"] <= body["summary"]["periods"]
    assert cls["reason"]
    assert str(cls["historical_mean"]) in cls["reason"]
    assert body["trend"] in ("INCREASING", "STABLE", "DECREASING")


def test_2_high_consumption_not_flagged_low(datasets):
    """Regression: the 9000 kWh/day HIGH dataset must never come out LOW just
    because its forecast is compared with an inflated daily/monthly baseline."""
    body = _classify(datasets["high_consumption"]["dataset_id"], 30)
    assert body["status"] != "LOW"
    cls = body["classification"]
    # The previous bug dragged the forecast ~14% below history; the anchored
    # seasonal-trend model keeps it inside the household's own band.
    assert body["summary"]["change_percent"] > -2.0
    assert cls["forecast_mean"] >= cls["historical_mean"] * 0.9


def test_3_high_peak_dataset_detects_high_periods(datasets):
    ds = datasets["high_peak"]["dataset_id"]
    body = _classify(ds, 7)
    cls = body["classification"]
    assert body["status"] == "HIGH"
    assert cls["high_period_count"] > 0
    assert cls["high_period_percentage"] > 0


def test_4_historical_stats_are_consistent_with_data(datasets):
    ds = datasets["high_consumption"]["dataset_id"]
    meta = datasets["high_consumption"]
    series_id = meta["dataset_id"]
    body = _classify(series_id, 30)
    cls = body["classification"]
    # high consumption: p90 of daily energy sits well above the daily mean.
    assert cls["historical_90th_percentile"] > cls["historical_mean"]
    assert cls["historical_mean"] > 8000


def test_5_forecast_stats_match_summary(datasets):
    body = _classify(datasets["household"]["dataset_id"], 30)
    cls = body["classification"]
    assert cls["forecast_change_percent"] == body["summary"]["change_percent"]
    assert abs(body["summary"]["average"] - cls["forecast_mean"]) / max(1.0, cls["forecast_mean"]) < 0.15


def test_6_high_period_percentage_is_consistent(datasets):
    body = _classify(datasets["high_peak"]["dataset_id"], 7)
    cls = body["classification"]
    expected = round(cls["high_period_count"] / max(1, len(body["points"])) * 100.0, 2)
    assert cls["high_period_percentage"] == expected


def test_7_forecast_peak_equals_summary_maximum(datasets):
    body = _classify(datasets["household"]["dataset_id"], 30)
    cls = body["classification"]
    assert cls["forecast_peak"] == body["summary"]["maximum"] == body["peak"]["value"]


def test_8_trend_band_is_configurable_default_10(datasets, monkeypatch):
    high = _classify(datasets["high_peak"]["dataset_id"], 7)
    assert high["trend"] == "INCREASING"
    # Narrowing the band to 1% turns the high_consumption -1.6% case into a
    # DECREASING; at the default 10% it is STABLE.
    import backend.app.services.user_forecast as uf

    monkeypatch.setattr(uf.api_config, "TREND_STABLE_THRESHOLD_PCT", 1.0)
    uf._run.cache_clear()
    body = _classify(datasets["high_consumption"]["dataset_id"], 12, "months")
    assert body["trend"] == "DECREASING"
    assert body["warning"] is not None


def test_9_reason_is_explainable_and_numeric(datasets):
    body = _classify(datasets["high_consumption"]["dataset_id"], 30)
    cls = body["classification"]
    assert "historical baseline" in cls["reason"]
    assert str(cls["forecast_mean"]) in cls["reason"]
    assert str(cls["historical_mean"]) in cls["reason"]
    # HIGH / LOW reasons call out the direction; MEDIUM calls out parity.
    assert "line with" in cls["reason"] or "above" in cls["reason"] or "below" in cls["reason"]


def test_10_below_baseline_warning_is_diagnostic(datasets, monkeypatch):
    """When the forecast mean drops significantly below the uploaded baseline the
    response carries a model-diagnostic warning instead of silently hiding it."""
    import backend.app.services.user_forecast as uf

    monkeypatch.setattr(uf.api_config, "TREND_STABLE_THRESHOLD_PCT", 1.0)
    uf._run.cache_clear()
    body = _classify(datasets["high_consumption"]["dataset_id"], 12, "months")
    cls = body["classification"]
    assert body["warning"] is not None
    assert cls["warning"] == body["warning"]
    assert "below" in body["warning"]
    assert cls["forecast_change_percent"] <= -1.0


def test_11_thresholds_always_household_relative(datasets):
    """Classification thresholds come from the household's own history, never a
    fixed universal value — a high-consumption household's HIGH threshold is far
    above a low-consumption one's."""
    low = _classify(datasets["high_peak"]["dataset_id"], 30)["classification"]
    high = _classify(datasets["high_consumption"]["dataset_id"], 30)["classification"]
    assert high["forecast_mean"] > low["forecast_mean"] * 10
    assert high["historical_mean"] > low["historical_mean"] * 10


# ---------------------------------------------------------------------------
# Household bill (household scope only)
# ---------------------------------------------------------------------------
def test_generate_household_bill_present_for_kwh(datasets):
    ds = datasets["household"]["dataset_id"]
    body = client.post(f"{API}/forecast/generate",
                       json={"dataset_id": ds, "horizon_value": 30, "horizon_unit": "days"}).json()
    bill = body["household_bill"]
    assert bill is not None
    assert bill["total"] > 0
    assert bill["forecasted_monthly_kwh"] > 0
    assert bill["tariff_unit"] == "INR/kWh"


def test_generate_regional_scope_never_gets_household_bill(datasets):
    ds = datasets["regional"]["dataset_id"]
    body = client.post(f"{API}/forecast/generate",
                       json={"dataset_id": ds, "horizon_value": 1, "horizon_unit": "days"}).json()
    assert body["scope"] == "regional_grid"
    assert body["unit"] == "MW"
    assert body["energy_unit"] == "MWh"
    assert body["household_bill"] is None


def test_generate_scope_override_regional(datasets):
    ds = datasets["household"]["dataset_id"]
    body = client.post(f"{API}/forecast/generate",
                       json={"dataset_id": ds, "horizon_value": 7, "horizon_unit": "days",
                             "scope": "regional_grid"}).json()
    assert body["scope"] == "regional_grid"
    assert body["unit"] == "MW"
    assert body["scope_detected_by"] == "user_override"
    assert body["household_bill"] is None


def test_generate_scope_override_household(datasets):
    ds = datasets["regional"]["dataset_id"]
    body = client.post(f"{API}/forecast/generate",
                       json={"dataset_id": ds, "horizon_value": 7, "horizon_unit": "days",
                             "scope": "household"}).json()
    assert body["scope"] == "household"
    assert body["unit"] == "kWh"
    assert body["scope_detected_by"] == "user_override"


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------
def test_csv_export_points(datasets):
    ds = datasets["household"]["dataset_id"]
    r = client.get(f"{API}/forecast/export",
                   params={"dataset_id": ds, "horizon_value": 30, "horizon_unit": "days"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[0] == ("timestamp,predicted_consumption,lower_bound,upper_bound,"
                        "classification,peak_flag,weather_available,temperature,humidity")
    assert len(lines) == 31  # header + 30 daily points
    assert any("HIGH" in ln or "LOW" in ln or "MEDIUM" in ln for ln in lines[1:])


def test_summary_export(datasets):
    ds = datasets["household"]["dataset_id"]
    r = client.get(f"{API}/forecast/export/summary",
                   params={"dataset_id": ds, "horizon_value": 30, "horizon_unit": "days"})
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert "--,Forecast summary" in text
    assert "forecast_type,medium_term" in text
    assert "household_hourly.csv" in text


def test_export_unknown_dataset_404():
    r = client.get(f"{API}/forecast/export",
                   params={"dataset_id": "ds_nope", "horizon_value": 1})
    assert r.status_code == 404