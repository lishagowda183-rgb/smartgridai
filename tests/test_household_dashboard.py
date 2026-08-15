"""Tests for the household dashboard + household analytics (Phase 11.5).

All numbers must come from the uploaded dataset only — no synthetic/sample
values. Weather sections must be reported as unavailable whenever the persisted
weather does not overlap the uploaded history (never fabricated).
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

from backend.app.main import app  # noqa: E402
from backend.app.services import upload_service  # noqa: E402

API = "/api/v1"
client = TestClient(app)
rng = np.random.default_rng(11)


def hourly_household_csv() -> bytes:
    """120 days of hourly kWh (mean ~400) — household scope, 2024 data."""
    idx = pd.date_range("2024-01-01", periods=120 * 24, freq="h")
    vals = 400 + 45 * np.sin(2 * np.pi * idx.hour / 24) + rng.normal(0, 8, len(idx))
    df = pd.DataFrame({"timestamp": idx.strftime("%Y-%m-%d %H:%M:%S"),
                       "consumption": vals.round(3)})
    return df.to_csv(index=False).encode("utf-8")


def _upload(content: bytes, filename: str = "household_hourly.csv") -> dict:
    r = client.post(f"{API}/forecast/upload",
                    files={"file": (filename, content, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def household_ds():
    upload_service.clear_uploads()
    return _upload(hourly_household_csv(), "household_hourly.csv")["dataset_id"]


# ---------------------------------------------------------------------------
# Datasets listing
# ---------------------------------------------------------------------------
def test_list_datasets_empty():
    upload_service.clear_uploads()
    r = client.get(f"{API}/forecast/datasets")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["datasets"] == []
    assert body["active_dataset_id"] is None


def test_list_datasets(household_ds):
    r = client.get(f"{API}/forecast/datasets")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert body["active_dataset_id"] == household_ds
    assert body["datasets"][0]["dataset_id"] == household_ds


# ---------------------------------------------------------------------------
# Dashboard onboarding
# ---------------------------------------------------------------------------
def test_dashboard_no_dataset_returns_onboarding_404():
    upload_service.clear_uploads()
    r = client.get(f"{API}/forecast/dashboard")
    assert r.status_code == 404
    assert "uploaded" in r.json()["error"]["message"].lower()


# ---------------------------------------------------------------------------
# Dashboard (uploaded data only)
# ---------------------------------------------------------------------------
def test_dashboard_household(household_ds):
    r = client.get(f"{API}/forecast/dashboard", params={"dataset_id": household_ds})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dataset_id"] == household_ds
    assert body["scope"] == "household"
    assert body["unit"] == "kWh"
    assert body["onboarding"] is False
    assert body["frequency"] == "hourly"

    current = body["current"]
    assert current["value"] > 0
    assert current["timestamp"]
    assert body["week"]["total"] > 0
    assert body["month"]["total"] > 0
    assert body["today"] is not None and body["today"]["value"] > 0
    assert body["tomorrow"] is not None and body["tomorrow"]["value"] > 0
    assert body["peak"]["value"] > 0
    assert body["status"] in ("LOW", "MEDIUM", "HIGH")
    assert body["household_bill"]["total"] > 0
    assert len(body["points"]) >= 7 * 24


def test_dashboard_weather_not_fabricated(household_ds):
    """Uploaded history (2024) does not overlap the persisted snapshot (2026),
    so the dashboard must report weather as unavailable — never fake it."""
    r = client.get(f"{API}/forecast/dashboard", params={"dataset_id": household_ds})
    assert r.status_code == 200
    weather = r.json()["weather"]
    assert weather is not None
    assert weather["status"] != "full"


def test_dashboard_unknown_dataset_404():
    r = client.get(f"{API}/forecast/dashboard", params={"dataset_id": "ds_nope"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Household analytics
# ---------------------------------------------------------------------------
def test_analytics_household_no_dataset_404():
    upload_service.clear_uploads()
    r = client.get(f"{API}/analytics/household")
    assert r.status_code == 404


def test_analytics_household(household_ds):
    r = client.get(f"{API}/analytics/household", params={"dataset_id": household_ds})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dataset_id"] == household_ds
    assert body["unit"] == "kWh"
    assert len(body["by_hour"]) == 24
    assert len(body["by_day_of_week"]) == 7
    assert len(body["by_month"]) == 4  # Jan-Apr
    assert body["peak_hours"]["peak_to_average_ratio"] > 0
    assert len(body["distribution"]) > 0
    assert len(body["monthly_trend"]) >= 3


def test_analytics_household_weather_overlap_honest(household_ds):
    """Weather correlations must be reported as unavailable (not fabricated)
    when the staged weather artifact does not overlap the uploaded history."""
    r = client.get(f"{API}/analytics/household", params={"dataset_id": household_ds})
    assert r.status_code == 200
    wc = r.json()["weather_correlations"]
    assert wc is not None
    assert wc["available"] is False
    assert "overlap" in wc["note"].lower()