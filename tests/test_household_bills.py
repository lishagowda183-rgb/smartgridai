"""Automated tests for the Phase 6 Household Bill Simulator.

Unit tests verify deterministic scalar arithmetic: flat-rate bills, slab
pricing across tiers, time-of-use peak/off-peak splitting (via the peak-share
assumption), what-if scenarios (+X% / -X% / custom / bill difference /
estimated peak-shift savings), tariff validation, determinism, and that every
result is labeled with scope="household" + kWh units. The household simulator
must remain fully separate from the regional grid engine (scope="regional_grid").
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
import household_bills as hb  # noqa: E402
import tariffs  # noqa: E402

FLAT = {
    "name": "h_flat",
    "currency": "INR",
    "unit_price_per_kwh": 6.0,
    "fixed_charge_per_month": 100.0,
    "tax_pct": 5.0,
    "additional_charges": 0.0,
}

SLAB = {
    "name": "h_slab",
    "currency": "INR",
    "slabs": [
        {"min_kwh": 0, "max_kwh": 100, "price_per_kwh": 3.5},
        {"min_kwh": 100, "max_kwh": 300, "price_per_kwh": 5.0},
        {"min_kwh": 300, "max_kwh": None, "price_per_kwh": 7.0},
    ],
    "fixed_charge_per_month": 200.0,
    "tax_pct": 5.0,
    "additional_charges": 25.0,
}

TOU = {
    "name": "h_tou",
    "currency": "INR",
    "unit_price_per_kwh": 5.5,
    "peak_hours": {"start": 17, "end": 22},
    "peak_multiplier": 1.5,
    "off_peak_price_per_kwh": 5.5,
    "fixed_charge_per_month": 150.0,
    "tax_pct": 5.0,
    "additional_charges": 0.0,
}


# ---------------------------------------------------------------------------
# 1. Tariff loading + validation
# ---------------------------------------------------------------------------
def test_household_tariffs_directory_has_samples() -> None:
    names = hb.available_household_tariffs()
    assert {"household_flat", "household_slabs", "household_tou"} <= set(names)


def test_load_household_tariff_validated() -> None:
    t = hb.load_household_tariff("household_slabs")
    assert t["name"] == "household_slabs"
    assert t["slabs"][0]["price_per_kwh"] > 0
    assert t["currency"] == "INR"


def test_validate_rejects_missing_pricing() -> None:
    with pytest.raises(hb.HouseholdTariffError):
        hb.validate_household_tariff({"name": "x", "fixed_charge_per_month": 1})


def test_validate_rejects_unknown_keys() -> None:
    with pytest.raises(hb.HouseholdTariffError):
        hb.validate_household_tariff({**FLAT, "bogus_key": 1})


def test_validate_rejects_bad_peak_hours() -> None:
    bad = {**FLAT, "peak_hours": {"start": 10, "end": 25}}
    with pytest.raises(hb.HouseholdTariffError):
        hb.validate_household_tariff(bad)


# ---------------------------------------------------------------------------
# 2. Flat-rate bill
# ---------------------------------------------------------------------------
def test_household_flat_350_kwh() -> None:
    bill = hb.compute_household_bill(350.0, FLAT)
    # energy = 350 * 6 = 2100; + fixed 100 -> 2200; +5% tax -> 2310.
    assert bill["energy_charge"] == 2100.0
    assert bill["fixed_charge"] == 100.0
    assert bill["taxes"] == round(2200 * 0.05, 2)
    assert bill["total"] == pytest.approx(2310.0)
    assert bill["monthly_consumption_kwh"] == 350.0


def test_household_flat_scope_and_units() -> None:
    bill = hb.compute_household_bill(350.0, FLAT)
    assert bill["scope"] == config.SCOPE_HOUSEHOLD == "household"
    assert bill["scope_label"] == config.SCOPE_HOUSEHOLD_LABEL
    assert bill["consumption_unit"] == "kWh"
    assert bill["energy_unit"] == "kWh"
    assert bill["tariff_unit"] == "INR/kWh"
    assert bill["reporting_period"] == "1 month"


# ---------------------------------------------------------------------------
# 3. Slab-based pricing (per-kWh tiers)
# ---------------------------------------------------------------------------
def test_household_slab_single_tier() -> None:
    bill = hb.compute_household_bill(50.0, SLAB)
    assert bill["energy_charge"] == 50 * 3.5
    assert len(bill["slab_breakdown"]) == 1


def test_household_slab_350_kwh_crosses_tiers() -> None:
    bill = hb.compute_household_bill(350.0, SLAB)
    # 100*3.5 + 200*5.0 + 50*7.0 = 350 + 1000 + 350 = 1700
    assert bill["energy_charge"] == pytest.approx(1700.0)
    parts = {r["min_kwh"]: r["charge"] for r in bill["slab_breakdown"]}
    assert parts[0.0] == pytest.approx(350.0)
    assert parts[100.0] == pytest.approx(1000.0)
    assert parts[300.0] == pytest.approx(350.0)
    # fixed 200 + additional 25 -> subtotal 1925, +5% tax.
    assert bill["total"] == pytest.approx((1700 + 200 + 25) * 1.05)


# ---------------------------------------------------------------------------
# 4. Time-of-use (peak-share assumption)
# ---------------------------------------------------------------------------
def test_household_tou_uses_peak_share() -> None:
    # 40% peak share: peak_kwh=140 at 8.25, off_peak_kwh=210 at 5.5.
    bill = hb.compute_household_bill(350.0, TOU, peak_share_pct=40.0)
    assert bill["peak_kwh"] == pytest.approx(140.0)
    assert bill["off_peak_kwh"] == pytest.approx(210.0)
    assert bill["energy_charge"] == pytest.approx(140 * 8.25 + 210 * 5.5)
    assert bill["assumption"] is not None
    assert "40%" in bill["assumption"]


def test_household_tou_peak_rate() -> None:
    assert hb.peak_rate_per_kwh(TOU) == 8.25
    assert hb.off_peak_rate_per_kwh(TOU) == 5.5


def test_household_flat_has_no_peak_charge() -> None:
    bill = hb.compute_household_bill(350.0, FLAT)
    assert bill["peak_kwh"] == 0.0
    assert bill["off_peak_kwh"] == 350.0
    assert bill["peak_charge"] == 0.0


# ---------------------------------------------------------------------------
# 5. What-if analysis
# ---------------------------------------------------------------------------
def test_what_if_plus_minus_custom() -> None:
    wi = hb.household_what_if(350.0, SLAB, custom_kwh=500.0)
    base = wi["base"]["total"]
    assert wi["minus_10pct"]["consumption_kwh"] == pytest.approx(315.0)
    assert wi["plus_10pct"]["consumption_kwh"] == pytest.approx(385.0)
    assert wi["custom"]["monthly_consumption_kwh"] == 500.0
    assert wi["custom"]["total"] > base
    # +10% bill exceeds base, -10% bill is below base.
    assert wi["plus_10pct"]["total"] > base
    assert wi["minus_10pct"]["total"] < base


def test_what_if_bill_difference() -> None:
    wi = hb.household_what_if(350.0, FLAT, custom_kwh=500.0)
    diff = wi["bill_difference"]
    assert diff["from_consumption_kwh"] == 350.0
    assert diff["to_consumption_kwh"] == 500.0
    # 500 kWh flat: total = (500*6+100)*1.05 = 3255; base 2310 -> +945.
    assert diff["amount"] == pytest.approx(3255.0 - 2310.0)
    assert diff["pct"] == pytest.approx(round((3255 / 2310 - 1) * 100, 2))


def test_what_if_peak_shift_savings_tou() -> None:
    wi = hb.household_what_if(350.0, TOU, peak_shift_pct=10.0)
    sv = wi["estimated_savings"]
    assert sv["applicable"] is True
    assert sv["shifted_kwh"] == pytest.approx(14.0)  # 10% of 140 peak kWh
    assert sv["savings_per_month"] == pytest.approx(14.0 * (8.25 - 5.5))


def test_what_if_no_savings_for_flat() -> None:
    wi = hb.household_what_if(350.0, FLAT)
    assert wi["estimated_savings"] is None


def test_what_if_deterministic() -> None:
    a = hb.household_what_if(350.0, SLAB, custom_kwh=420.0)
    b = hb.household_what_if(350.0, SLAB, custom_kwh=420.0)
    assert a == b


# ---------------------------------------------------------------------------
# 6. Input validation
# ---------------------------------------------------------------------------
def test_negative_consumption_rejected() -> None:
    with pytest.raises(hb.HouseholdTariffError):
        hb.compute_household_bill(-10.0, FLAT)


def test_invalid_peak_share_rejected() -> None:
    with pytest.raises(hb.HouseholdTariffError):
        hb.compute_household_bill(350.0, TOU, peak_share_pct=120.0)


# ---------------------------------------------------------------------------
# 7. Separation from the regional grid engine
# ---------------------------------------------------------------------------
def test_regional_engine_scope_is_regional_grid() -> None:
    idx = pd.date_range("2020-01-01", periods=24, freq="h")
    s = pd.Series(np.full(len(idx), 1.0), index=idx)
    bill = tariffs.compute_bill(s, tariffs.load_tariff("simple_flat"))
    assert bill["scope"] == config.SCOPE_REGIONAL_GRID == "regional_grid"
    assert bill["scope_label"] == config.SCOPE_REGIONAL_LABEL
    assert bill["consumption_unit"] == "MW"
    assert bill["energy_unit"] == "MWh"
    assert bill["tariff_unit"] == "INR/MWh"
    assert bill["reporting_period"] is not None