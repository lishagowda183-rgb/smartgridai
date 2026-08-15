"""Automated tests for the Phase 6 tariff and bill engine.

Unit tests verify deterministic arithmetic: flat-rate bills, slab pricing,
fixed charges, taxes/additional charges, peak/off-peak splitting, horizon
resolution, what-if percentage changes, peak-shift savings, tariff JSON
validation and determinism. Report-level tests check the ingested history and
persisted artifacts when the pipeline has been run.
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

import bill_engine as be  # noqa: E402
import config  # noqa: E402
import tariffs  # noqa: E402

FLAT = {
    "name": "test_flat",
    "unit_price_per_mwh": 100.0,
    "fixed_charge_per_month": 10.0,
    "tax_pct": 10.0,
    "additional_charges": 5.0,
}

SLAB = {
    "name": "test_slab",
    "slabs": [
        {"min_mwh": 0, "max_mwh": 100, "price_per_mwh": 50.0},
        {"min_mwh": 100, "max_mwh": 200, "price_per_mwh": 80.0},
        {"min_mwh": 200, "max_mwh": None, "price_per_mwh": 120.0},
    ],
    "fixed_charge_per_month": 20.0,
    "tax_pct": 0.0,
}

TOU = {
    "name": "test_tou",
    "unit_price_per_mwh": 100.0,
    "peak_hours": {"start": 17, "end": 22},
    "peak_multiplier": 1.5,
    "off_peak_price_per_mwh": 60.0,
    "fixed_charge_per_month": 0.0,
    "tax_pct": 0.0,
}


def series_of(energy_values: list[float], start: str = "2020-01-01") -> pd.Series:
    """Hourly series with the given consumption values."""
    idx = pd.date_range(start, periods=len(energy_values), freq="h")
    return pd.Series(energy_values, index=idx, name=config.CLEANED_COLUMN)


# ---------------------------------------------------------------------------
# 1. Tariff loading + validation
# ---------------------------------------------------------------------------
def test_tariffs_directory_has_sample_tariffs() -> None:
    names = tariffs.available_tariffs()
    assert {"simple_flat", "domestic_slabs", "time_of_use"} <= set(names)


def test_load_tariff_returns_validated_dict() -> None:
    t = tariffs.load_tariff("simple_flat")
    assert t["name"] == "simple_flat"
    assert t["unit_price_per_mwh"] > 0


def test_load_tariff_unknown_name_raises() -> None:
    with pytest.raises(tariffs.TariffValidationError):
        tariffs.load_tariff("does_not_exist")


def test_validate_rejects_missing_pricing() -> None:
    with pytest.raises(tariffs.TariffValidationError):
        tariffs.validate_tariff({"name": "x", "fixed_charge_per_month": 1})


def test_validate_rejects_unknown_keys() -> None:
    with pytest.raises(tariffs.TariffValidationError):
        tariffs.validate_tariff({**FLAT, "bogus_key": 1})


def test_validate_rejects_bad_peak_hours() -> None:
    bad = {**FLAT, "peak_hours": {"start": 10, "end": 25}}
    with pytest.raises(tariffs.TariffValidationError):
        tariffs.validate_tariff(bad)


# ---------------------------------------------------------------------------
# 2. Flat-rate bill (deterministic arithmetic)
# ---------------------------------------------------------------------------
def test_flat_bill_items() -> None:
    s = series_of([10.0] * 2)  # 20 MWh in 2 hours
    bill = tariffs.compute_bill(s, FLAT)
    assert bill["energy_mwh"] == 20.0
    assert bill["energy_charge"] == 20.0 * 100.0
    assert bill["fixed_charge"] == 10.0
    assert bill["additional_charges"] == 5.0
    assert bill["taxes"] == round((2000 + 10 + 5) * 0.10, 2)
    expected_total = 2000 + 10 + 5 + bill["taxes"]
    assert bill["total"] == pytest.approx(expected_total)
    assert bill["peak_mwh"] == 0.0 and bill["off_peak_mwh"] == 20.0


def test_regional_bill_scope_and_unit_metadata() -> None:
    s = series_of([10.0] * 2)
    bill = tariffs.compute_bill(s, FLAT)
    assert bill["scope"] == config.SCOPE_REGIONAL_GRID == "regional_grid"
    assert bill["scope_label"] == config.SCOPE_REGIONAL_LABEL == "Regional Grid Energy Cost"
    assert bill["consumption_unit"] == config.CONSUMPTION_UNIT == "MW"
    assert bill["energy_unit"] == config.ENERGY_UNIT == "MWh"
    assert bill["tariff_unit"] == "INR/MWh"
    assert bill["reporting_period"] == "2020-01"


def test_energy_kwh_is_mwh_times_kwh_per_mwh() -> None:
    s = series_of([10.0] * 2)  # 20 MWh in 2 hours
    bill = tariffs.compute_bill(s, FLAT)
    assert bill["energy_kwh"] == pytest.approx(bill["energy_mwh"] * config.KWH_PER_MWH)
    assert bill["energy_kwh"] == pytest.approx(20_000.0)
    assert config.KWH_PER_MWH == 1000


def test_household_scale_series_has_no_regional_sanity_note() -> None:
    s = series_of([10.0] * 24)  # 240 MWh/month, far below regional scale
    bill = tariffs.compute_bill(s, FLAT)
    assert bill["sanity_notes"] == []


def test_flat_bill_taxes_tax_the_subtotal() -> None:
    s = series_of([1.0] * 50)  # 50 MWh, no fixed, no additional
    t = {"name": "t", "unit_price_per_mwh": 2.0, "fixed_charge_per_month": 0.0,
         "tax_pct": 10.0, "additional_charges": 0.0}
    bill = tariffs.compute_bill(s, t)
    assert bill["energy_charge"] == 100.0
    assert bill["taxes"] == 10.0
    assert bill["total"] == 110.0


# ---------------------------------------------------------------------------
# 3. Slab-based pricing
# ---------------------------------------------------------------------------
def test_slab_single_tier() -> None:
    s = series_of([1.0] * 50)  # 50 MWh -> first slab at 50.0
    bill = tariffs.compute_bill(s, SLAB)
    assert bill["energy_charge"] == 50 * 50.0
    assert len(bill["slab_breakdown"]) == 1


def test_slab_crosses_two_tiers() -> None:
    s = series_of([1.0] * 150)  # 150 MWh
    bill = tariffs.compute_bill(s, SLAB)
    parts = {r["min_mwh"]: r["charge"] for r in bill["slab_breakdown"]}
    assert parts[0.0] == pytest.approx(100 * 50.0)
    assert parts[100.0] == pytest.approx(50 * 80.0)
    assert bill["energy_charge"] == pytest.approx(5000 + 4000)


def test_slab_crosses_three_tiers() -> None:
    s = series_of([1.0] * 250)  # 250 MWh
    bill = tariffs.compute_bill(s, SLAB)
    assert bill["energy_charge"] == pytest.approx(100 * 50 + 100 * 80 + 50 * 120)


def test_slab_price_per_mwh_selection() -> None:
    assert tariffs.slab_price_per_mwh(SLAB, 50) == 50.0
    assert tariffs.slab_price_per_mwh(SLAB, 150) == 80.0
    assert tariffs.slab_price_per_mwh(SLAB, 250) == 120.0


# ---------------------------------------------------------------------------
# 4. Peak / off-peak rates
# ---------------------------------------------------------------------------
def test_tou_splits_peak_and_offpeak() -> None:
    idx = pd.date_range("2020-01-01", periods=24, freq="h")
    values = np.ones(24)  # 1 MWh every hour
    s = pd.Series(values, index=idx)
    bill = tariffs.compute_bill(s, TOU)
    # Peak hours 17..22 -> 6 hours of 1 MWh = 6 MWh at 150. Off-peak 18 MWh at 60.
    assert bill["peak_mwh"] == 6.0
    assert bill["off_peak_mwh"] == 18.0
    assert bill["energy_charge"] == pytest.approx(6 * 150 + 18 * 60)


def test_rate_for_hour_tou() -> None:
    assert tariffs.rate_for_hour(TOU, 10) == 60.0  # off-peak
    assert tariffs.rate_for_hour(TOU, 17) == 150.0  # peak start
    assert tariffs.rate_for_hour(TOU, 22) == 150.0  # peak end


def test_flat_tariff_has_no_peak_split() -> None:
    s = series_of([1.0] * 24)
    bill = tariffs.compute_bill(s, FLAT)
    assert bill["peak_mwh"] == 0.0 and bill["off_peak_mwh"] == 24.0
    assert bill["energy_charge"] == pytest.approx(24 * 100.0)


def test_offpeak_explicit_price() -> None:
    t = {**FLAT, "peak_hours": {"start": 0, "end": 5}, "off_peak_price_per_mwh": 50.0}
    s = series_of([1.0] * 24)
    bill = tariffs.compute_bill(s, t)
    assert bill["energy_charge"] == pytest.approx(6 * 100.0 + 18 * 50.0)


# ---------------------------------------------------------------------------
# 5. Horizon resolution (user-driven forecasting range)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("spec", "hours"),
    [
        ("2d", 48),
        ("30d", 720),
        ("1m", 720),
        ("2m", 1440),
        ("1y", 8760),
        ("7d", 168),
    ],
)
def test_resolve_horizon(spec: str, hours: int) -> None:
    assert be.resolve_horizon(spec) == hours


def test_resolve_horizon_invalid() -> None:
    with pytest.raises(ValueError):
        be.resolve_horizon("fortnight")


# ---------------------------------------------------------------------------
# 6. What-if + comparison (deterministic deltas)
# ---------------------------------------------------------------------------
def test_percentage_change() -> None:
    assert tariffs.percentage_change(100.0, 110.0) == 10.0
    assert tariffs.percentage_change(100.0, 90.0) == -10.0
    assert tariffs.percentage_change(0.0, 5.0) == 0.0


def test_what_if_consumption_increases() -> None:
    idx = pd.date_range("2020-01-01", periods=24 * 31, freq="h")  # ~1 month
    s = pd.Series(np.full(len(idx), 1.0), index=idx)
    t = FLAT
    base = tariffs.compute_bill(s, t)
    up = be.what_if_consumption(s, t, 10.0)
    assert up["energy_mwh"] == pytest.approx(base["energy_mwh"] * 1.1)


def test_what_if_consumption_decreases() -> None:
    idx = pd.date_range("2020-01-01", periods=24 * 31, freq="h")
    s = pd.Series(np.full(len(idx), 1.0), index=idx)
    t = FLAT
    base = tariffs.compute_bill(s, t)
    down = be.what_if_consumption(s, t, -10.0)
    assert down["energy_mwh"] == pytest.approx(base["energy_mwh"] * 0.9)


def test_peak_shift_savings_nonnegative_and_applicable() -> None:
    idx = pd.date_range("2020-01-01", periods=24 * 31, freq="h")
    s = pd.Series(np.full(len(idx), 1.0), index=idx)
    res = be.peak_shift_savings(s, TOU, shift_pct=20.0)
    assert res["applicable"] is True
    assert res["estimated_savings"] > 0
    # saving = shifted_mwh * (peak_rate - off_peak_rate)
    assert res["estimated_savings"] == pytest.approx(
        res["shifted_mwh"] * (150.0 - 60.0)
    )


def test_peak_shift_savings_period_label_present() -> None:
    idx = pd.date_range("2020-01-01", periods=24 * 31, freq="h")
    s = pd.Series(np.full(len(idx), 1.0), index=idx)
    res = be.peak_shift_savings(s, TOU, shift_pct=20.0)
    assert res["period_label"] == "2020-01"


def test_peak_shift_savings_assumption_documented() -> None:
    idx = pd.date_range("2020-01-01", periods=24 * 31, freq="h")
    s = pd.Series(np.full(len(idx), 1.0), index=idx)
    res = be.peak_shift_savings(s, TOU, shift_pct=20.0)
    assert "assumption" in res
    assert "2020-01" in res["assumption"]
    assert "20.0%" in res["assumption"]


def test_peak_shift_not_applicable_for_flat() -> None:
    idx = pd.date_range("2020-01-01", periods=24 * 31, freq="h")
    s = pd.Series(np.full(len(idx), 1.0), index=idx)
    res = be.peak_shift_savings(s, FLAT)
    assert res["applicable"] is False


# ---------------------------------------------------------------------------
# 7. Determinism
# ---------------------------------------------------------------------------
def test_compute_bill_deterministic() -> None:
    s = series_of([1.0, 2.0, 3.0, 4.0, 5.0])
    a = tariffs.compute_bill(s, TOU)
    b = tariffs.compute_bill(s, TOU)
    assert a == b


# ---------------------------------------------------------------------------
# 8. Artifacts (skipped until bill_engine runs)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def series() -> pd.Series:
    if not config.FEATURES_DATA.exists():
        pytest.skip("feature artifact missing. Run feature_engineering.py first.")
    df = pd.read_parquet(config.FEATURES_DATA)
    df.index = pd.to_datetime(df.index)
    return df[config.CLEANED_COLUMN]


def test_historical_bill_count(series: pd.Series) -> None:
    t = tariffs.load_tariff("simple_flat")
    history = tariffs.compute_monthly_bills(series, t)
    assert len(history) >= 40  # ~4 full years of monthly bills


def test_regional_scale_produces_sanity_note(series: pd.Series) -> None:
    t = tariffs.load_tariff("simple_flat")
    bill = tariffs.compute_bill(series, t)
    # Regional grid load sums to tens of thousands of MWh for a month, far
    # beyond a household meter; the engine must flag this instead of silently
    # presenting the grid-scale bill as a household bill.
    assert bill["energy_mwh"] > 100_000
    assert any("regional" in n.lower() for n in bill["sanity_notes"])
    assert bill["energy_kwh"] == pytest.approx(bill["energy_mwh"] * config.KWH_PER_MWH)


def test_peak_shift_savings_period_matches_current_bill_period(series: pd.Series) -> None:
    t = tariffs.load_tariff("time_of_use")
    savings = be.peak_shift_savings(series, t)
    current = be.current_bill(series, t)
    assert savings["applicable"] is True
    assert savings["period_label"] == current["period_label"]
    assert savings["estimated_savings"] > 0
    assert savings["assumption"]


def test_peak_shift_savings_by_month_periods_match_bill_history(series: pd.Series) -> None:
    t = tariffs.load_tariff("time_of_use")
    by_month = be.peak_shift_savings_by_month(series, t)
    history = tariffs.compute_monthly_bills(series, t)
    assert len(by_month) == len(history) > 0
    assert {r["period_label"] for r in by_month} == set(history["period"])
    # Every per-month estimate is labeled with its own month and > 0.
    assert all(r["estimated_savings"] > 0 for r in by_month)
    assert all(r["period_label"] for r in by_month)


def test_peak_shift_savings_by_month_ignores_flat_tariff(series: pd.Series) -> None:
    t = tariffs.load_tariff("simple_flat")
    assert be.peak_shift_savings_by_month(series, t) == []


def test_bill_report_exists() -> None:
    assert config.BILL_REPORT.exists(), (
        "bill_report.json missing. Run `python ml/scripts/bill_engine.py` first."
    )


def test_bill_report_keys() -> None:
    report = json.loads(config.BILL_REPORT.read_text(encoding="utf-8"))
    assert {"current_bill", "comparison", "forecasted_bill",
            "monthly_estimated_bill", "what_if"} <= set(report)
    assert "tariff" in report
    assert "change_vs_previous_pct" in report["comparison"]


def test_bill_report_regional_grid_labeling() -> None:
    report = json.loads(config.BILL_REPORT.read_text(encoding="utf-8"))
    assert report["mode"] == "regional_grid"
    assert report["units"]["scope"] == "regional_grid"
    assert report["units"]["scope_label"] == "Regional Grid Energy Cost"
    assert report["units"]["tariff_unit"] == "INR/MWh"
    assert report["current_bill"]["scope"] == "regional_grid"
    assert report["current_bill"]["reporting_period"] == report["current_bill"]["period_label"]


def test_bill_report_peak_shift_savings_labeled_by_period() -> None:
    report = json.loads(config.BILL_REPORT.read_text(encoding="utf-8"))
    ps = report["what_if"]["peak_shift_savings"]
    assert ps["period_label"] == report["current_bill"]["period_label"]
    assert ps["estimated_savings"] == pytest.approx(2_045_355_550.0)
    assert "hypothetically shifted" in ps["assumption"]


def test_bill_report_peak_shift_savings_by_month() -> None:
    report = json.loads(config.BILL_REPORT.read_text(encoding="utf-8"))
    by_month = report["what_if"]["peak_shift_savings_by_month"]
    assert isinstance(by_month, list) and len(by_month) >= 40
    assert config.PEAK_SHIFT_SAVINGS_CSV.exists()


def test_bill_history_csv_and_plot_exist() -> None:
    assert config.BILL_HISTORY_CSV.exists()
    assert config.BILL_HISTORY_PLOT.exists()