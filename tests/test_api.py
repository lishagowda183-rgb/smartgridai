"""Automated tests for the Phase 7 FastAPI backend.

Uses FastAPI's TestClient (httpx). No external network calls: weather endpoints
serve the persisted Open-Meteo artifact, forecasts reuse the trained model and
the regional bill default serves the cached bill_report.json. The single slow
test (regional recompute) is marked and runs last.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.main import app  # noqa: E402

API = "/api/v1"
client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _warm():
    client.get(f"{API}/consumption/current")
    yield


# ---------------------------------------------------------------------------
# Health / meta
# ---------------------------------------------------------------------------
def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["prefix"] == API
    assert body["app"]


def test_docs_and_redoc_available():
    for path in ("/docs", "/redoc"):
        r = client.get(path)
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]


def test_openapi_json_has_expected_paths():
    r = client.get(f"{API}/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    for endpoint in (
        "/consumption/current",
        "/consumption/history",
        "/forecast/hourly",
        "/forecast/daily",
        "/forecast/monthly",
        "/weather/current",
        "/weather/forecast",
        "/analytics/hourly",
        "/analytics/weekly",
        "/analytics/monthly",
        "/analytics/peak-hours",
        "/analytics/weather-relationship",
        "/anomalies",
        "/bills/regional",
        "/bills/regional/tariffs",
        "/bills/household/calculate",
        "/bills/household/what-if",
        "/bills/household/tariffs",
        "/agent/chat",
    ):
        assert f"{API}{endpoint}" in paths, f"missing {endpoint}"


# ---------------------------------------------------------------------------
# Consumption
# ---------------------------------------------------------------------------
def test_consumption_current():
    r = client.get(f"{API}/consumption/current")
    assert r.status_code == 200
    body = r.json()
    assert body["unit"] == "MW"
    assert body["count"] > 20_000
    assert body["latest"]["value_mw"] > 0
    assert len(body["trailing_24h"]) == 24


def test_consumption_history_default_and_filtered():
    r = client.get(f"{API}/consumption/history")
    assert r.status_code == 200
    assert r.json()["returned"] == 1_000

    r = client.get(
        f"{API}/consumption/history",
        params={"start": "2015-01-08 05:00:00", "end": "2015-01-08 23:00:00", "limit": 48},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["returned"] == 19
    assert body["total_matching"] == body["returned"]
    assert body["points"][0]["timestamp"].startswith("2015-01-08")


def test_consumption_history_invalid_date():
    r = client.get(f"{API}/consumption/history", params={"start": "not-a-date"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_REQUEST"


# ---------------------------------------------------------------------------
# Forecast (real iterated model forecast)
# ---------------------------------------------------------------------------
def test_forecast_hourly():
    r = client.get(f"{API}/forecast/hourly", params={"hours": 24})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 24
    assert body["unit"] == "MW"
    assert body["model"]
    assert body["points"][0]["timestamp"] < body["points"][-1]["timestamp"]


def test_forecast_hourly_valid_horizons():
    for hours in (24, 48, 72):
        r = client.get(f"{API}/forecast/hourly", params={"hours": hours})
        assert r.status_code == 200
        assert r.json()["count"] == hours


def test_forecast_hourly_invalid_horizon():
    r = client.get(f"{API}/forecast/hourly", params={"hours": 12})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_REQUEST"


def test_forecast_daily_and_monthly():
    r = client.get(f"{API}/forecast/daily", params={"days": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["energy_unit"] == "MWh"
    assert body["days"]
    assert body["days"][0]["energy_mwh"] > 0

    r = client.get(f"{API}/forecast/monthly", params={"months": 1})
    assert r.status_code == 200
    assert r.json()["months"]


def test_forecast_hourly_out_of_range_param_rejected():
    r = client.get(f"{API}/forecast/daily", params={"days": 999})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Weather (persisted artifact, no network)
# ---------------------------------------------------------------------------
def test_weather_current():
    r = client.get(f"{API}/weather/current")
    assert r.status_code == 200
    body = r.json()
    assert body["source"].endswith("weather_forecast.json")
    assert "condition" in body["current"]
    assert body["current"]["temperature_c"] is not None


def test_weather_forecast_days():
    r = client.get(f"{API}/weather/forecast", params={"days": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["returned_hours"] == 24
    assert body["points"][0]["time"] < body["points"][-1]["time"]


def test_weather_forecast_invalid_days():
    r = client.get(f"{API}/weather/forecast", params={"days": 0})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
def test_analytics_profiles():
    r = client.get(f"{API}/analytics/hourly")
    assert r.status_code == 200
    assert len(r.json()["points"]) == 24

    r = client.get(f"{API}/analytics/weekly")
    assert r.status_code == 200
    assert len(r.json()["points"]) == 7

    r = client.get(f"{API}/analytics/monthly")
    assert r.status_code == 200
    assert len(r.json()["points"]) == 12


def test_analytics_peak_hours():
    r = client.get(f"{API}/analytics/peak-hours")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["peak_hour_of_day"] == 19
    assert body["summary"]["max_demand"]["value"] > 40_000
    assert isinstance(body["morning_peak_days"], int)


def test_analytics_weather_relationship():
    r = client.get(f"{API}/analytics/weather-relationship")
    assert r.status_code == 200
    body = r.json()
    assert body["n_rows"] == 34_860
    assert body["unit"] == "MW"
    variables = {c["variable"] for c in body["correlations"]}
    assert variables == {"temperature", "humidity", "precipitation", "wind_speed"}
    temp = next(c for c in body["correlations"] if c["variable"] == "temperature")
    assert -1.0 <= temp["pearson"] <= 1.0
    assert temp["pearson"] == pytest.approx(0.103, abs=0.03)
    assert body["temperature_buckets"]
    for b in body["temperature_buckets"]:
        assert b["mean_consumption_mw"] > 0
        assert b["count"] > 0


# ---------------------------------------------------------------------------
# Anomalies
# ---------------------------------------------------------------------------
def test_anomalies_default():
    r = client.get(f"{API}/anomalies")
    assert r.status_code == 200
    body = r.json()
    assert body["counts_by_severity"]
    assert body["returned"] <= 500


def test_anomalies_filtered():
    r = client.get(f"{API}/anomalies", params={"severity": "high", "method": "isolation_forest", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert all(a["severity"] == "high" for a in body["anomalies"])
    assert all(a["method"] == "isolation_forest" for a in body["anomalies"])
    assert body["returned"] <= 5


def test_anomalies_invalid_filter():
    r = client.get(f"{API}/anomalies", params={"severity": "bogus"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_REQUEST"


# ---------------------------------------------------------------------------
# Bills — Regional Grid Energy Cost (two-mode contract)
# ---------------------------------------------------------------------------
def test_regional_bill_cached_contract():
    r = client.get(f"{API}/bills/regional")
    assert r.status_code == 200
    body = r.json()
    assert body["_served_from"] == "cache"
    assert body["mode"] == "regional_grid"
    assert body["units"]["scope"] == "regional_grid"
    assert body["units"]["consumption_unit"] == "MW"
    assert body["units"]["energy_unit"] == "MWh"
    assert body["units"]["tariff_unit"] == "INR/MWh"
    assert body["current_bill"]["total"] == 77_898_211_912.5
    assert body["current_bill"]["period_label"] == "2018-12"
    assert "forecasted_bill" in body


def test_regional_bill_unknown_tariff_404():
    r = client.get(f"{API}/bills/regional", params={"tariff": "nope"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_regional_tariffs_list():
    r = client.get(f"{API}/bills/regional/tariffs")
    assert r.status_code == 200
    assert set(r.json()["tariffs"]) == {"domestic_slabs", "simple_flat", "time_of_use"}


def test_regional_bill_recompute():
    r = client.get(f"{API}/bills/regional", params={"tariff": "time_of_use", "horizon": "1m", "recompute": True})
    assert r.status_code == 200
    body = r.json()
    assert body["_served_from"] == "recomputed"
    assert body["mode"] == "regional_grid"
    assert body["tariff"]["name"] == "time_of_use"


# ---------------------------------------------------------------------------
# Bills — Household Bill Simulator (per-kWh, fully separate)
# ---------------------------------------------------------------------------
def test_household_calculate_known_example():
    r = client.post(
        f"{API}/bills/household/calculate",
        json={"monthly_kwh": 350, "tariff": "household_slabs"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "household"
    assert body["scope_label"] == "Household Bill Simulator"
    assert body["consumption_unit"] == "kWh"
    assert body["energy_unit"] == "kWh"
    assert body["tariff_unit"] == "INR/kWh"
    assert body["reporting_period"] == "1 month"
    assert body["total"] == 2_021.25


def test_household_calculate_tou_peak_share():
    r = client.post(
        f"{API}/bills/household/calculate",
        json={"monthly_kwh": 350, "tariff": "household_tou", "peak_share_pct": 40},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["peak_kwh"] == 140.0
    assert body["off_peak_kwh"] == 210.0


def test_household_calculate_validation_422():
    r = client.post(f"{API}/bills/household/calculate", json={"monthly_kwh": -5})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_household_calculate_missing_consumption_422():
    r = client.post(f"{API}/bills/household/calculate", json={"tariff": "household_slabs"})
    assert r.status_code == 422


def test_household_calculate_zero_consumption():
    r = client.post(
        f"{API}/bills/household/calculate",
        json={"monthly_kwh": 0, "tariff": "household_slabs"},
    )
    assert r.status_code == 200
    body = r.json()
    # 0 kWh -> energy 0 + fixed 200 + additional 25 = 225; tax 5% = 11.25 => 236.25
    assert body["monthly_consumption_kwh"] == 0.0
    assert body["energy_charge"] == 0.0
    assert body["total"] == 236.25


def test_household_calculate_flat_tariff():
    r = client.post(
        f"{API}/bills/household/calculate",
        json={"monthly_kwh": 350, "tariff": "household_flat"},
    )
    assert r.status_code == 200
    body = r.json()
    # 350 kWh * 6.0 = 2100 + fixed 100 = 2200 + tax 5% = 110 => 2310
    assert body["total"] == 2_310.0


def test_household_calculate_unknown_tariff_404():
    r = client.post(f"{API}/bills/household/calculate", json={"monthly_kwh": 350, "tariff": "bogus"})
    assert r.status_code == 404


def test_household_what_if():
    r = client.post(
        f"{API}/bills/household/what-if",
        json={"monthly_kwh": 350, "tariff": "household_tou", "custom_kwh": 300},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "household"
    assert body["plus_10pct"]["total"] > body["base"]["total"]
    assert body["minus_10pct"]["total"] < body["base"]["total"]
    assert body["custom"]["total"] < body["base"]["total"]
    assert body["estimated_savings"]["applicable"] is True
    assert body["estimated_savings"]["savings_per_month"] > 0


def test_household_what_if_invalid_peak_share_422():
    r = client.post(
        f"{API}/bills/household/what-if",
        json={"monthly_kwh": 350, "peak_share_pct": 150},
    )
    assert r.status_code == 422


def test_household_tariffs_list():
    r = client.get(f"{API}/bills/household/tariffs")
    assert r.status_code == 200
    assert set(r.json()["tariffs"]) == {"household_flat", "household_slabs", "household_tou"}
