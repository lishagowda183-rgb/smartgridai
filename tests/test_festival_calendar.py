"""Automated tests for Phase 12 — festival / holiday-aware forecasting.

Covers: the deterministic pan-Indian calendar (festival + national holidays),
per-timestamp festival feature columns, the historical household observation
layer (HIGHER/LOWER/SIMILAR learned strictly from the uploaded data),
future-festival detection inside the horizon, the multiplicative adjustment
(only when data is sufficient AND outside the similar band), the ``festivals``
response block, festival recommendations and end-to-end API integration for
both household and regional scope. No external network requests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.main import app  # noqa: E402
from backend.app.services import festival_calendar as fc  # noqa: E402
from backend.app.services import upload_service  # noqa: E402

API = "/api/v1"
client = TestClient(app)
rng = np.random.default_rng(11)


def _hourly_diwali_series(periods: int = 365, boost: float = 1.4) -> pd.Series:
    """Hourly kWh starting 2024-06-01 with a strong Diwali window boost."""
    idx = pd.date_range("2024-06-01", periods=periods * 24, freq="h")
    base = (
        30
        + 12 * np.sin(2 * np.pi * (idx.dayofyear - 315) / 365)
        + 8 * np.sin(2 * np.pi * idx.hour / 24)
        + rng.normal(0, 1.5, len(idx))
    )
    m = (idx >= "2024-10-29") & (idx <= "2024-11-04")
    vals = np.where(m, base * boost, base)
    return pd.Series(vals, index=idx)


def _daily_series(periods: int = 365) -> pd.Series:
    idx = pd.date_range("2024-06-01", periods=periods, freq="D")
    vals = 30 + 12 * np.sin(2 * np.pi * (idx.dayofyear - 315) / 365) + rng.normal(0, 2, len(idx))
    return pd.Series(np.maximum(5.0, vals), index=idx)


def _hourly_csv_bytes(periods: int = 365, boost: float = 1.4) -> bytes:
    idx = pd.date_range("2024-06-01", periods=periods * 24, freq="h")
    base = (
        30
        + 12 * np.sin(2 * np.pi * (idx.dayofyear - 315) / 365)
        + 8 * np.sin(2 * np.pi * idx.hour / 24)
        + rng.normal(0, 1.5, len(idx))
    )
    m = (idx >= "2024-10-29") & (idx <= "2024-11-04")
    vals = np.where(m, base * boost, base)
    df = pd.DataFrame({"timestamp": idx.strftime("%Y-%m-%d %H:%M:%S"),
                       "consumption": vals.round(3)})
    return df.to_csv(index=False).encode("utf-8")


def _upload(content: bytes, filename: str = "festival_hourly.csv") -> dict:
    r = client.post(f"{API}/forecast/upload",
                    files={"file": (filename, content, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def datasets():
    upload_service.clear_uploads()
    return {
        "hourly_boost": _upload(_hourly_csv_bytes(), "festival_hourly_boost.csv"),
        "daily": _upload(
            pd.DataFrame({
                "timestamp": pd.date_range("2024-06-01", periods=365, freq="D").strftime("%Y-%m-%d"),
                "consumption_kwh": _daily_series().round(2).values,
            }).to_csv(index=False).encode("utf-8"),
            "festival_daily.csv",
        ),
        "regional": _upload(
            pd.DataFrame({
                "timestamp": pd.date_range("2024-06-01", periods=30 * 24, freq="h").strftime("%Y-%m-%d %H:%M:%S"),
                "total_load_actual": (30000 + 4500 * np.sin(np.arange(30 * 24) / 24) + rng.normal(0, 1000, 30 * 24)).round(2),
            }).to_csv(index=False).encode("utf-8"),
            "festival_regional.csv",
        ),
    }


# ---------------------------------------------------------------------------
# Calendar layer (deterministic, scope-independent)
# ---------------------------------------------------------------------------
def test_calendar_returns_sorted_deterministic_occurrences():
    a = fc.festival_occurrences(pd.Timestamp("2024-01-01"), pd.Timestamp("2025-01-01"))
    b = fc.festival_occurrences(pd.Timestamp("2024-01-01"), pd.Timestamp("2025-01-01"))
    dates_a = [(o["name"], str(o["date"].date())) for o in a]
    dates_b = [(o["name"], str(o["date"].date())) for o in b]
    assert dates_a == dates_b  # deterministic
    assert all(o["date"] >= pd.Timestamp("2024-01-01") for o in a)
    assert all(o["date"] < pd.Timestamp("2025-01-01") for o in a)
    # Sorted by (date, name).
    assert all(a[i]["date"] <= a[i + 1]["date"] for i in range(len(a) - 1))
    assert any(o["name"] == "Diwali" for o in a)


def test_calendar_includes_fixed_national_holidays():
    occs = fc.festival_occurrences(pd.Timestamp("2024-01-01"), pd.Timestamp("2025-01-01"))
    holidays = {(o["name"], str(o["date"].date())) for o in occs if o["national_holiday"]}
    assert ("Republic Day", "2024-01-26") in holidays
    assert ("Independence Day", "2024-08-15") in holidays
    assert ("Gandhi Jayanti", "2024-10-02") in holidays
    assert ("Christmas", "2024-12-25") in holidays


def test_calendar_occurrences_track_lunisolar_drift():
    # Diwali moves each year: 2024-11-01, 2025-10-20, 2026-11-08 (curated table).
    diwali = lambda y: fc.festival_occurrences(pd.Timestamp(y, 1, 1), pd.Timestamp(y + 1, 1, 1),
                                               festival="Diwali")
    assert str(diwali(2024)[0]["date"].date()) == "2024-11-01"
    assert str(diwali(2025)[0]["date"].date()) == "2025-10-20"
    assert str(diwali(2026)[0]["date"].date()) == "2026-11-08"


def test_calendar_filters_by_festival_name():
    days = fc.festival_occurrences(pd.Timestamp("2024-06-01"), pd.Timestamp("2025-06-01"),
                                   festival="Eid al-Fitr")
    assert {o["name"] for o in days} == {"Eid al-Fitr"}
    assert not days[0]["national_holiday"]  # lunisolar festival, not a national holiday


def test_window_limits_respect_config(monkeypatch):
    import backend.app.services.festival_calendar as m
    monkeypatch.setattr(m.api_config, "FESTIVAL_WINDOW_BEFORE", 2)
    monkeypatch.setattr(m.api_config, "FESTIVAL_WINDOW_AFTER", 3)
    lo, hi = fc.window_limits(pd.Timestamp("2025-10-20"))
    assert lo == pd.Timestamp("2025-10-18")
    assert hi == pd.Timestamp("2025-10-23")


# ---------------------------------------------------------------------------
# Per-timestamp feature columns
# ---------------------------------------------------------------------------
def test_festival_features_flags_window_and_proximity():
    idx = pd.date_range("2025-10-16", periods=10, freq="D")
    feats = fc.festival_features(idx)
    # Diwali 2025-10-20, window 20-3 .. 20+3 = 10-17 .. 10-23.
    assert feats.loc["2025-10-17", "is_festival"] == 1
    assert feats.loc["2025-10-20", "festival_day"] == 1
    assert feats.loc["2025-10-20", "is_holiday"] == 1
    assert feats.loc["2025-10-17", "days_before_festival"] == 3
    assert feats.loc["2025-10-21", "days_after_festival"] == 1
    # Outside the window.
    assert feats.loc["2025-10-16", "is_festival"] == 0
    assert feats.loc["2025-10-16", "festival_window"] == 0
    assert feats.loc["2025-10-16", "festival_name"] == ""
    # Weekend flag is a real calendar fact.
    assert int(feats.loc["2025-10-18", "is_weekend"]) == 1  # Saturday


def test_festival_features_empty_index():
    feats = fc.festival_features(pd.DatetimeIndex([]))
    assert list(feats.columns) == [
        "is_festival", "festival_name", "is_holiday", "is_weekend",
        "days_before_festival", "days_after_festival", "festival_day",
        "festival_window",
    ]


# ---------------------------------------------------------------------------
# Historical household observation layer
# ---------------------------------------------------------------------------
def test_insufficient_daily_history_reports_no_effect():
    series = _daily_series()  # single year -> one festival window, ~7 obs
    analysis = fc.analyze_historical_festivals(series)
    diwali = next(a for a in analysis if a["festival_name"] == "Diwali")
    assert diwali["data_available"] is False
    assert diwali["note"] == fc.INSUFFICIENT_MESSAGE
    assert "observation_count" in diwali and "minimum_observations" in diwali
    # No fabricated effect numbers.
    assert "difference_percent" not in diwali


def test_sufficient_hourly_history_detects_higher_effect():
    series = _hourly_diwali_series()
    analysis = fc.analyze_historical_festivals(series)
    diwali = next(a for a in analysis if a["festival_name"] == "Diwali")
    assert diwali["data_available"] is True
    assert diwali["observation_count"] >= fc._min_observations()
    assert diwali["classification"] == "HIGHER_THAN_NORMAL"
    assert diwali["difference_percent"] > 15.0
    assert diwali["festival_average_kwh"] > diwali["normal_average_kwh"]
    assert "baseline_method" in diwali


def test_sufficient_hourly_history_detects_lower_effect():
    series = _hourly_diwali_series(boost=0.5)
    analysis = fc.analyze_historical_festivals(series)
    diwali = next(a for a in analysis if a["festival_name"] == "Diwali")
    assert diwali["data_available"] is True
    assert diwali["classification"] == "LOWER_THAN_NORMAL"
    assert diwali["difference_percent"] < -15.0


def test_analyze_handles_no_history():
    assert fc.analyze_historical_festivals(pd.Series(dtype=float)) == []
    assert fc.analyze_historical_festivals(None) == []


def test_classify_effect_bands(monkeypatch):
    monkeypatch.setattr(fc.api_config, "FESTIVAL_EFFECT_THRESHOLD_PCT", 10.0)
    assert fc.classify_effect(10.0) == "HIGHER_THAN_NORMAL"
    assert fc.classify_effect(9.99) == "SIMILAR_TO_NORMAL"
    assert fc.classify_effect(0.0) == "SIMILAR_TO_NORMAL"
    assert fc.classify_effect(-10.0) == "LOWER_THAN_NORMAL"
    assert fc.classify_effect(-4.0) == "SIMILAR_TO_NORMAL"


# ---------------------------------------------------------------------------
# Future festivals + forecast adjustment
# ---------------------------------------------------------------------------
def test_upcoming_festivals_inside_horizon_only():
    series = _hourly_diwali_series()
    analysis = fc.analyze_historical_festivals(series)
    upcoming = fc.upcoming_festivals(series.index.max(), 365, analysis)  # through 2025-06-30
    names = {u["festival_name"] for u in upcoming}
    # Diwali 2025 falls inside the horizon; Diwali 2026 does not.
    assert "Diwali" in names
    assert all(pd.Timestamp(u["date"]) <= series.index.max() + pd.Timedelta(days=365)
               for u in upcoming)
    diwali = next(u for u in upcoming if u["festival_name"] == "Diwali")
    assert diwali["date"] == "2025-10-20"
    assert diwali["window_start"] == "2025-10-17"
    assert diwali["window_end"] == "2025-10-23"
    assert diwali["festival_data_available"] is True
    assert diwali["historical_classification"] == "HIGHER_THAN_NORMAL"
    assert diwali["note"] == "Based on historical household data."


def test_upcoming_national_holiday_flagged_without_effect():
    series = _daily_series()
    analysis = fc.analyze_historical_festivals(series)
    upcoming = fc.upcoming_festivals(series.index.max(), 365, analysis)
    christmas = next(u for u in upcoming if u["festival_name"] == "Christmas")
    assert christmas["national_holiday"] is True
    assert christmas["festival_data_available"] is False
    assert christmas["historical_effect_percent"] is None
    assert christmas["note"] == fc.INSUFFICIENT_MESSAGE


def test_adjust_forecast_applies_only_outside_similar_band():
    forecast = pd.Series([100.0] * 20, index=pd.date_range("2025-10-15", periods=20, freq="D"))
    upcoming = [
        {
            "festival_name": "Diwali", "date": "2025-10-20",
            "window_start": "2025-10-17", "window_end": "2025-10-23",
            "festival_data_available": True, "festival_effect_percent": 26.0,
        },
        {
            # SIMILAR effect: must NOT move the forecast, even though "available".
            "festival_name": "Holi", "date": "2026-03-04",
            "window_start": "2026-03-01", "window_end": "2026-03-07",
            "festival_data_available": True, "festival_effect_percent": 3.0,
        },
    ]
    adjusted, applied = fc.adjust_forecast(forecast, upcoming)
    diwali_days = (adjusted.index >= "2025-10-17") & (adjusted.index <= "2025-10-23")
    non_diwali = ~diwali_days
    assert np.allclose(adjusted[diwali_days].values, 100.0 * 1.26)
    assert np.allclose(adjusted[non_diwali].values, 100.0)
    assert len(applied) == 1
    assert applied[0]["festival_name"] == "Diwali"
    assert applied[0]["applied_multiplier"] == 1.26


def test_adjust_forecast_respects_lower_effect_and_clip():
    forecast = pd.Series(
        [100.0] * 20,
        index=pd.date_range("2025-06-01", periods=20, freq="D"),
    )
    upcoming = [
        {
            "festival_name": "Eid al-Adha", "date": "2025-06-06",
            "window_start": "2025-06-03", "window_end": "2025-06-09",
            "festival_data_available": True, "festival_effect_percent": -30.0,
        },
    ]
    adjusted, applied = fc.adjust_forecast(forecast, upcoming)
    window = (adjusted.index >= "2025-06-03") & (adjusted.index <= "2025-06-09")
    assert np.allclose(adjusted[window].values, 70.0)
    assert applied[0]["applied_multiplier"] == 0.7


def test_adjust_forecast_clips_runaway_multiplier():
    forecast = pd.Series([100.0] * 7, index=pd.date_range("2025-10-17", periods=7, freq="D"))
    upcoming = [{
        "festival_name": "D", "date": "2025-10-20",
        "window_start": "2025-10-17", "window_end": "2025-10-23",
        "festival_data_available": True, "festival_effect_percent": 200.0,
    }]
    adjusted, applied = fc.adjust_forecast(forecast, upcoming)
    assert np.allclose(adjusted.values, 150.0)  # clipped at 1.5
    assert applied[0]["applied_multiplier"] == 1.5


def test_adjust_forecast_empty_returns_empty():
    out, applied = fc.adjust_forecast(None, [])
    assert out is None and applied == []


def test_festivals_payload_structure():
    series = _hourly_diwali_series()
    payload = fc.festivals_payload(series, 30, weather_used=False, forecast_type="medium_term")
    assert set(payload) == {"analysis", "upcoming", "calendar_note", "note", "weather_note"}
    assert payload["calendar_note"]
    assert "KNOWN from the deterministic calendar" in payload["note"]
    assert "Weather data unavailable" in payload["weather_note"]


# ---------------------------------------------------------------------------
# End-to-end API integration
# ---------------------------------------------------------------------------
def _generate(ds: str, hv: int, hu: str = "days") -> dict:
    r = client.post(f"{API}/forecast/generate",
                    json={"dataset_id": ds, "horizon_value": hv, "horizon_unit": hu})
    assert r.status_code == 200, r.text
    return r.json()


def test_generate_returns_festivals_block_for_household(datasets):
    body = _generate(datasets["hourly_boost"]["dataset_id"], 30)
    f = body["festivals"]
    assert set(f) == {
        "analysis", "upcoming", "calendar_note", "note", "weather_note",
        "applied", "weather_available",
    }
    assert len(f["upcoming"]) >= 1
    assert all(u["window_start"] <= u["date"] <= u["window_end"] for u in f["upcoming"])
    # Analysis is always computed from the uploaded history.
    assert any(a["festival_name"] == "Diwali" for a in f["analysis"])


@patch("backend.app.services.user_forecast.pd.Timestamp.now")
def test_generate_applies_observed_effect_when_data_is_sufficient(
    _mock_now, datasets
):
    _mock_now.return_value = pd.Timestamp("2025-06-01", tz=None)
    body = _generate(datasets["hourly_boost"]["dataset_id"], 365)
    f = body["festivals"]
    diwali = next(u for u in f["upcoming"] if u["festival_name"] == "Diwali")
    assert diwali["festival_data_available"] is True
    assert diwali["historical_classification"] == "HIGHER_THAN_NORMAL"
    assert any(
        a["festival_name"] == "Diwali" and a["data_available"]
        for a in f["analysis"]
    )
    # The observed effect is applied to the forecast window.
    assert any(a["festival_name"] == "Diwali" and "applied_multiplier" in a
               for a in f["applied"])
    # The response carries the matching festival recommendation.
    assert any(r["id"] == "festival_higher" for r in body["recommendations"])


def test_generate_never_fabricates_effect_for_insufficient_history(datasets):
    body = _generate(datasets["daily"]["dataset_id"], 365)
    f = body["festivals"]
    for a in f["analysis"]:
        if a["data_available"]:
            continue
        assert a["note"] == fc.INSUFFICIENT_MESSAGE
        assert "difference_percent" not in a
    # Nothing gets applied silently either.
    assert f["applied"] == []
    assert any(r["id"] == "festival_insufficient_data" for r in body["recommendations"])


def test_generate_regional_scope_also_gets_calendar_block(datasets):
    body = _generate(datasets["regional"]["dataset_id"], 365)
    assert body["scope"] == "regional_grid"
    f = body["festivals"]
    # Calendar facts are scope-independent (always returned even for a grid).
    assert len(f["upcoming"]) >= 1
    names = {u["festival_name"] for u in f["upcoming"]}
    assert "Diwali" in names  # 2024-11-01 lies inside the 365-day horizon
    assert "weather_available" in f
    # Analysis only reflects festivals OBSERVABLE in the uploaded history;
    # this 30-day history (Jun–Jul) contains none, yet the block still exists.
    assert isinstance(f["analysis"], list)


def test_festival_feature_columns_in_forecast_points(datasets):
    body = _generate(datasets["hourly_boost"]["dataset_id"], 7)
    p = body["points"][0]
    assert "is_festival" in p and "festival_name" in p and "is_holiday" in p
    assert p["is_festival"] in (True, False)


def test_calendar_override_json_is_honored(tmp_path, monkeypatch):
    overrides = tmp_path / "calendar.json"
    overrides.write_text('{"Diwali": {"2025": [10, 29]}}', encoding="utf-8")
    monkeypatch.setattr(fc.api_config, "FESTIVAL_CALENDAR_JSON", str(overrides))
    days = fc.festival_occurrences(pd.Timestamp("2025-01-01"), pd.Timestamp("2026-01-01"),
                                   festival="Diwali")
    assert len(days) == 1
    assert str(days[0]["date"].date()) == "2025-10-29"