"""Automated tests for Phase 4.1 — weather as a core forecasting feature.

Covers honest weather metadata (weather_status / weather_available /
weather_source / weather_features_used / weather_note), the automatic Open-Meteo
snapshot refresh (ensure_snapshot with a freshness TTL, cache fallback and a
``temporarily_unavailable`` failure mode), the always-rendered dashboard weather
section (temperature / humidity / precipitation / wind + status/source), and the
AI assistant's weather-aware routing ("how does weather affect my usage?",
"will the weather increase my electricity usage?").

Everything is deterministic: the persisted snapshot is treated as fresh, the
network fetch is monkeypatched, and no live Open-Meteo request is ever made.
"""

from __future__ import annotations

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
_SCRIPTS = PROJECT_ROOT / "ml" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from backend.app.agent.provider import MockProvider, _describe_tool_result  # noqa: E402
from backend.app.agent.schemas import ConversationStore  # noqa: E402
from backend.app.agent.service import AgentService  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.services import upload_service, user_forecast, weather  # noqa: E402

API = "/api/v1"
client = TestClient(app)
rng = np.random.default_rng(21)


# ---------------------------------------------------------------------------
# Deterministic guards: never hit the network, never write the snapshot.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _no_live_api(monkeypatch):
    monkeypatch.setattr(weather, "snapshot_age_hours", lambda: 0.0)
    monkeypatch.setattr(weather, "_fetch_and_persist",
                        lambda: (_ for _ in ()).throw(AssertionError("network in tests")))
    yield
    user_forecast._run.cache_clear()


@pytest.fixture()
def household_ds():
    upload_service.clear_uploads()
    idx = pd.date_range("2024-01-01", periods=120 * 24, freq="h")
    base = 400 + 45 * np.sin(2 * np.pi * idx.hour / 24)
    vals = np.clip(base + rng.normal(0, 8, len(idx)), 120, 700)
    df = pd.DataFrame({"timestamp": idx.strftime("%Y-%m-%d %H:%M:%S"),
                       "consumption": vals.round(3)})
    r = client.post(f"{API}/forecast/upload",
                    files={"file": ("household_hourly.csv",
                                    df.to_csv(index=False).encode("utf-8"), "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["dataset_id"]


def _snapshot_payload(start: str = "2024-01-01T00:00", hours: int = 24 * 30,
                      temps=15.0) -> dict:
    times = pd.date_range(start, periods=hours, freq="h").strftime("%Y-%m-%dT%H:%M")
    return {
        "latitude": 40.4168, "longitude": -3.7038, "timezone": "Europe/Madrid",
        "timezone_abbreviation": "CET", "elevation": 667.0,
        "current": {"time": times[-1], "temperature_2m": temps,
                    "relative_humidity_2m": 62.0, "precipitation": 0.2,
                    "wind_speed_10m": 8.1, "weather_code": 3},
        "hourly": {
            "time": list(times),
            "temperature_2m": [temps] * len(times),
            "relative_humidity_2m": [62.0] * len(times),
            "precipitation": [0.2] * len(times),
            "wind_speed_10m": [8.1] * len(times),
            "weather_code": [3] * len(times),
        },
        "_generated_at": "2026-08-15T00:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# 1–3: weather metadata block (honest availability / source / features)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("status,forecast_type,weather_used,expected_source,expected_features", [
    ({"status": "full", "label": "available",
      "note": "Weather-aware forecast"}, "short_term",
     ["temperature", "humidity"], "Open-Meteo", ["temperature", "humidity"]),
    ({"status": "partial", "label": "partially available",
      "note": "part"}, "short_term",
     ["temperature"], "Open-Meteo", ["temperature"]),
    ({"status": "none", "label": "unavailable", "note": "none"}, "short_term",
     [], None, []),
    ({"status": "not_available", "label": "long-term historical pattern",
      "note": "Long-term forecast uses historical weather relationships and "
              "seasonal patterns"}, "long_term",
     [], "Open-Meteo (historical/seasonal patterns)", []),
])
def test_1_to_3_weather_block_available_source_and_features(
        status, forecast_type, weather_used, expected_source, expected_features):
    block = user_forecast._weather_block(status, forecast_type, weather_used)
    assert block["status"] == status["status"]
    assert block["weather_status"] == status["status"]
    assert block["weather_source"] == expected_source
    assert block["weather_features_used"] == expected_features
    assert block["weather_note"] == status["note"]
    assert block["weather_available"] == (expected_source is not None)
    # Existing keys are preserved (never dropped).
    assert {"status", "label", "note"} <= set(block.keys())


# ---------------------------------------------------------------------------
# 4: forecast response carries the weather_* metadata
# ---------------------------------------------------------------------------
def test_4_generate_response_has_weather_metadata(household_ds, monkeypatch):
    monkeypatch.setattr("backend.app.services.cache.load_weather_forecast",
                        lambda: _snapshot_payload())
    body = client.post(f"{API}/forecast/generate",
                       json={"dataset_id": household_ds,
                             "horizon_value": 7, "horizon_unit": "days"}).json()
    w = body["weather"]
    for key in ("status", "weather_status", "weather_available", "weather_source",
                "weather_features_used", "weather_note"):
        assert key in w, key
    assert w["weather_status"] in ("full", "partial", "none", "not_available")
    # Festival+weather block is preserved alongside.
    assert body["festivals"] is not None
    assert "weather_available" in body["festivals"]


def test_5_long_term_forecast_never_fabricates_weather(household_ds):
    body = client.post(f"{API}/forecast/generate",
                       json={"dataset_id": household_ds,
                             "horizon_value": 1, "horizon_unit": "years"}).json()
    assert body["forecast_type"] == "long_term"
    w = body["weather"]
    assert w["weather_status"] == "not_available"
    assert w["weather_available"] is True  # historical/seasonal patterns, labelled
    assert w["weather_source"] == "Open-Meteo (historical/seasonal patterns)"
    assert "historical weather relationships" in (w["weather_note"] or "")


def test_6_weather_status_full_when_snapshot_overlaps(monkeypatch):
    series = pd.Series(np.ones(24 * 10) * 10.0,
                       index=pd.date_range("2024-05-01", periods=24 * 10, freq="h"))
    monkeypatch.setattr("backend.app.services.cache.load_weather_forecast",
                        lambda: _snapshot_payload(start="2024-05-01T00:00"))
    status = user_forecast.weather_status(series, 7, "short_term")
    assert status["status"] == "full"


# ---------------------------------------------------------------------------
# 7–10: automatic snapshot refresh (fresh / stale / failure)
# ---------------------------------------------------------------------------
def test_7_ensure_snapshot_fresh_does_not_fetch():
    result = weather.ensure_snapshot()
    assert result["status"] == "ok"
    assert result["action"] == "fresh"


def test_8_ensure_snapshot_stale_fetches(monkeypatch):
    calls = {"n": 0}

    def fake_fetch(forecast_days=None):
        calls["n"] += 1

    monkeypatch.setattr(weather, "snapshot_age_hours", lambda: 50.0)
    monkeypatch.setattr(weather, "_fetch_and_persist", fake_fetch)
    result = weather.ensure_snapshot()
    assert result["status"] == "ok"
    assert result["action"] == "refreshed"
    assert calls["n"] == 1


def test_9_ensure_snapshot_failure_temporarily_unavailable(monkeypatch):
    monkeypatch.setattr(weather, "snapshot_age_hours", lambda: None)

    def failing_fetch(forecast_days=None):
        raise ConnectionError("offline")

    monkeypatch.setattr(weather, "_fetch_and_persist", failing_fetch)
    result = weather.ensure_snapshot()
    assert result["status"] == "temporarily_unavailable"
    assert "offline" in result["reason"]


def test_10_ensure_snapshot_failure_keeps_cached_snapshot(monkeypatch):
    monkeypatch.setattr(weather, "snapshot_age_hours", lambda: 7.5)

    def failing_fetch():
        raise ConnectionError("offline")

    monkeypatch.setattr(weather, "_fetch_and_persist", failing_fetch)
    result = weather.ensure_snapshot()
    assert result["status"] == "cache_fallback"
    assert result["age_hours"] == 7.5


# ---------------------------------------------------------------------------
# 11: dashboard always exposes a weather section + current observation
# ---------------------------------------------------------------------------
def test_11_dashboard_weather_section_and_current_observation(household_ds,
                                                              monkeypatch):
    monkeypatch.setattr("backend.app.services.cache.load_weather_forecast",
                        lambda: _snapshot_payload())
    r = client.get(f"{API}/forecast/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert "weather" in data and data["weather"] is not None
    assert "weather_now" in data
    now = data["weather_now"]
    assert now and now.get("observation") is not None
    obs = now["observation"]
    assert obs["temperature_c"] == pytest.approx(15.0)
    assert obs["humidity_pct"] == 62.0
    assert obs["precipitation_mm"] == 0.2
    assert obs["wind_speed_kmh"] == 8.1


# ---------------------------------------------------------------------------
# 12–14: AI assistant weather-aware routing + grounded formatting
# ---------------------------------------------------------------------------
def _agent() -> AgentService:
    return AgentService(provider=MockProvider(), store=ConversationStore(ttl_s=3600))


def test_12_agent_weather_relationship_routes_to_analytics(household_ds):
    resp = _agent().chat("How does weather affect my electricity usage?")
    assert resp["tools_used"] == ["get_user_analytics"]
    assert resp["scope"] == "household"


def test_13_agent_weather_increase_uses_weather_and_forecast(household_ds):
    resp = _agent().chat("Will the weather increase my electricity usage?")
    assert resp["tools_used"] == ["get_weather", "get_user_forecast"]
    assert resp["scope"] == "household"
    assert resp["data_points"]  # grounded real numbers, never invented


def test_14_classification_formatter_mentions_weather_when_available():
    payload = {
        "available": True, "status": "MEDIUM", "scope": "household", "unit": "kWh",
        "trend": "STABLE",
        "reason": "Forecast in line with baseline.",
        "classification": {"label": "medium", "forecast_mean": 400.0,
                           "historical_mean": 400.0, "forecast_change_percent": 0.0,
                           "high_period_percentage": 10.0, "high_period_count": 1},
        "weather": {"status": "full", "label": "available",
                    "weather_status": "full", "weather_source": "Open-Meteo",
                    "weather_available": True},
    }
    text = _describe_tool_result("get_household_classification", payload)
    assert "Weather is available" in text
    assert "Open-Meteo" in text


# ---------------------------------------------------------------------------
# 15: no network is touched during a forecast when the snapshot is fresh
# ---------------------------------------------------------------------------
def test_15_no_network_when_snapshot_fresh(household_ds, monkeypatch):
    import download_weather as dw

    def forbidden(*_args, **_kwargs):
        raise AssertionError("live network call during tests")

    monkeypatch.setattr(dw, "fetch_json", forbidden)
    body = client.post(f"{API}/forecast/generate",
                       json={"dataset_id": household_ds,
                             "horizon_value": 7, "horizon_unit": "days"}).json()
    assert "weather" in body  # forecast succeeds without any network request