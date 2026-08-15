"""Phase 6: Household Bill Simulator (fully separate from the regional grid bill).

This module models a *single household* electricity bill. Unlike the regional
grid engine (ml/scripts/tariffs.py), which prices an hourly regional-load series
in MW -> MWh against per-MWh tariffs, the household simulator prices a plain
monthly consumption figure (kWh) against per-kWh tariffs.

Everything here is scalar, deterministic, pure and unit-tested. Household
tariffs live in ml/household_tariffs/*.json and are kept completely separate
from the regional per-MWh tariffs in ml/tariffs/ (scope="household" vs
scope="regional_grid").

Time-of-use: a single monthly kWh figure has no hourly shape, so the peak /
off-peak split is driven by an explicit ``peak_share_pct`` assumption
(default 40% of monthly consumption at peak hours). This assumption is
recorded in the returned bill so it is never silent.
"""

from __future__ import annotations

import json
import logging
import sys
from math import inf

import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("household_bills")


class HouseholdTariffError(ValueError):
    """Raised when a household tariff or a billing input is invalid."""


def available_household_tariffs() -> list[str]:
    """Names of every household tariff defined in ml/household_tariffs/."""
    if not config.HOUSEHOLD_TARIFFS_DIR.is_dir():
        return []
    names = []
    for path in sorted(config.HOUSEHOLD_TARIFFS_DIR.glob("*.json")):
        try:
            names.append(json.loads(path.read_text(encoding="utf-8"))["name"])
        except (json.JSONDecodeError, KeyError):
            continue
    return names


def list_household_tariffs() -> list[dict]:
    """Load + validate every household tariff file."""
    if not config.HOUSEHOLD_TARIFFS_DIR.is_dir():
        raise FileNotFoundError(
            f"household tariffs directory missing: {config.HOUSEHOLD_TARIFFS_DIR}"
        )
    return [validate_household_tariff(json.loads(p.read_text(encoding="utf-8")))
            for p in sorted(config.HOUSEHOLD_TARIFFS_DIR.glob("*.json"))]


def load_household_tariff(name: str | None = None) -> dict:
    """Load + validate a household tariff by name (defaults to household_slabs)."""
    selection = name or "household_slabs"
    for path in config.HOUSEHOLD_TARIFFS_DIR.glob("*.json"):
        t = json.loads(path.read_text(encoding="utf-8"))
        if t.get("name") == selection:
            return validate_household_tariff(t)
    raise HouseholdTariffError(
        f"unknown household tariff '{selection}'. Available: {available_household_tariffs()}"
    )


def validate_household_tariff(t: dict) -> dict:
    """Validate a household (per-kWh) tariff against the supported schema."""
    if not isinstance(t, dict):
        raise HouseholdTariffError("tariff must be a JSON object")
    name = t.get("name")
    if not isinstance(name, str) or not name.strip():
        raise HouseholdTariffError("tariff requires a non-empty string 'name'")

    has_unit = isinstance(t.get("unit_price_per_kwh"), (int, float))
    slabs = t.get("slabs")
    has_slabs = isinstance(slabs, list) and len(slabs) > 0
    if not (has_unit or has_slabs):
        raise HouseholdTariffError(
            "tariff requires 'unit_price_per_kwh' or a non-empty 'slabs' list"
        )
    if has_unit and not has_slabs and t.get("unit_price_per_kwh") < 0:
        raise HouseholdTariffError("'unit_price_per_kwh' cannot be negative")

    if has_slabs:
        for i, slab in enumerate(slabs):
            if not isinstance(slab, dict):
                raise HouseholdTariffError(f"slab[{i}] must be an object")
            if "min_kwh" not in slab or "price_per_kwh" not in slab:
                raise HouseholdTariffError(
                    f"slab[{i}] requires 'min_kwh' and 'price_per_kwh'"
                )
            if slab.get("price_per_kwh", 0) < 0:
                raise HouseholdTariffError(f"slab[{i}] price cannot be negative")

    for key in ("fixed_charge_per_month", "tax_pct", "additional_charges"):
        val = t.get(key, 0.0)
        if not isinstance(val, (int, float)) or val < 0:
            raise HouseholdTariffError(f"'{key}' must be a non-negative number")

    peak = t.get("peak_hours")
    if peak is not None:
        if not isinstance(peak, dict) or "start" not in peak or "end" not in peak:
            raise HouseholdTariffError("'peak_hours' requires 'start' and 'end'")
        start, end = peak["start"], peak["end"]
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start <= end <= 23:
            raise HouseholdTariffError("'peak_hours' start/end must be hours in 0..23")
    if "peak_multiplier" in t:
        if not isinstance(t["peak_multiplier"], (int, float)) or t["peak_multiplier"] <= 0:
            raise HouseholdTariffError("'peak_multiplier' must be a positive number")
    if "off_peak_price_per_kwh" in t:
        if not isinstance(t["off_peak_price_per_kwh"], (int, float)) or t["off_peak_price_per_kwh"] < 0:
            raise HouseholdTariffError("'off_peak_price_per_kwh' cannot be negative")

    allowed = {
        "name", "display_name", "currency", "unit_price_per_kwh", "slabs",
        "fixed_charge_per_month", "tax_pct", "additional_charges", "peak_hours",
        "peak_multiplier", "off_peak_price_per_kwh", "billing_cycle",
    }
    unknown = set(t) - allowed
    if unknown:
        raise HouseholdTariffError(f"unknown tariff keys: {sorted(unknown)}")
    return t


def _tariff_unit(t: dict) -> str:
    """Per-kWh tariff unit string using the tariff currency."""
    currency = t.get("currency", config.CURRENCY_SYMBOL)
    return f"{currency}/kWh"


def peak_rate_per_kwh(t: dict) -> float:
    """Peak price per kWh (peak_multiplier applied on unit_price_per_kwh)."""
    if "peak_multiplier" in t:
        return float(t["unit_price_per_kwh"]) * float(t["peak_multiplier"])
    return float(t["unit_price_per_kwh"])


def off_peak_rate_per_kwh(t: dict) -> float:
    """Off-peak price per kWh (explicit off-peak rate or the base rate)."""
    return float(t.get("off_peak_price_per_kwh", t.get("unit_price_per_kwh", 0.0)))


def slab_breakdown(t: dict, monthly_kwh: float) -> list[dict]:
    """Marginal slab breakdown in kWh (which kWh fall into each tier)."""
    if "slabs" not in t:
        return []
    rows: list[dict] = []
    remaining = monthly_kwh
    for slab in t["slabs"]:
        lower, price = float(slab["min_kwh"]), float(slab["price_per_kwh"])
        upper = float(slab["max_kwh"]) if slab.get("max_kwh") is not None else inf
        taken = max(0.0, min(remaining, upper - lower))
        if taken > 0 or upper == inf:
            rows.append(
                {
                    "min_kwh": lower,
                    "max_kwh": None if upper == inf else upper,
                    "kwh": round(taken, 3),
                    "price_per_kwh": price,
                    "charge": round(taken * price, 2),
                }
            )
        remaining = max(0.0, remaining - taken)
        if remaining == 0:
            break
    return rows


def compute_household_bill(
    monthly_consumption_kwh: float,
    tariff: dict,
    peak_share_pct: float = 40.0,
) -> dict:
    """Compute an itemized household bill for a monthly kWh consumption.

    Returns a fully-labeled bill with scope="household", kWh units and an
    explicit reporting_period, so it is never confused with the regional grid
    bill (scope="regional_grid").
    """
    monthly_consumption_kwh = float(monthly_consumption_kwh)
    if monthly_consumption_kwh < 0:
        raise HouseholdTariffError("monthly consumption (kWh) cannot be negative")
    if not isinstance(peak_share_pct, (int, float)) or not 0 <= peak_share_pct <= 100:
        raise HouseholdTariffError("peak_share_pct must be between 0 and 100")

    if "slabs" in tariff:
        slab_rows = slab_breakdown(tariff, monthly_consumption_kwh)
        charge = sum(float(r["charge"]) for r in slab_rows)
        peak_kwh, off_peak_kwh = 0.0, monthly_consumption_kwh
        peak_charge, off_peak_charge = 0.0, charge
        assumption = None
    elif tariff.get("peak_hours") is not None:
        peak_kwh = monthly_consumption_kwh * peak_share_pct / 100.0
        off_peak_kwh = monthly_consumption_kwh - peak_kwh
        peak_rate = peak_rate_per_kwh(tariff)
        off_rate = off_peak_rate_per_kwh(tariff)
        peak_charge = peak_kwh * peak_rate
        off_peak_charge = off_peak_kwh * off_rate
        charge = peak_charge + off_peak_charge
        slab_rows = []
        peak = tariff["peak_hours"]
        assumption = (
            f"Peak-share assumption: {peak_share_pct:g}% of the monthly "
            f"{monthly_consumption_kwh:,.0f} kWh ({peak_kwh:,.1f} kWh) is billed at "
            f"the peak rate (h{peak['start']}-h{peak['end']}) and the remaining "
            f"{off_peak_kwh:,.1f} kWh at the off-peak rate."
        )
    else:
        charge = monthly_consumption_kwh * float(tariff["unit_price_per_kwh"])
        slab_rows = []
        peak_kwh, off_peak_kwh = 0.0, monthly_consumption_kwh
        peak_charge, off_peak_charge = 0.0, charge
        assumption = None

    fixed = float(tariff.get("fixed_charge_per_month", 0.0))
    additional = float(tariff.get("additional_charges", 0.0))
    subtotal = charge + fixed + additional
    taxes = round(subtotal * float(tariff.get("tax_pct", 0.0)) / 100.0, 2)

    return {
        "scope": config.SCOPE_HOUSEHOLD,
        "scope_label": config.SCOPE_HOUSEHOLD_LABEL,
        "reporting_period": "1 month",
        "consumption_unit": "kWh",
        "energy_unit": "kWh",
        "tariff_unit": _tariff_unit(tariff),
        "period_start": None,
        "period_end": None,
        "monthly_consumption_kwh": round(monthly_consumption_kwh, 3),
        "energy_kwh": round(monthly_consumption_kwh, 3),
        "peak_kwh": round(peak_kwh, 3),
        "off_peak_kwh": round(off_peak_kwh, 3),
        "energy_charge": round(charge, 2),
        "slab_breakdown": slab_rows,
        "peak_charge": round(peak_charge, 2),
        "off_peak_charge": round(off_peak_charge, 2),
        "fixed_charge": round(fixed, 2),
        "additional_charges": round(additional, 2),
        "tax_pct": float(tariff.get("tax_pct", 0.0)),
        "taxes": taxes,
        "assumption": assumption,
        "sanity_notes": [],
        "total": round(subtotal + taxes, 2),
    }


def household_what_if(
    monthly_consumption_kwh: float,
    tariff: dict,
    plus_pct: float = 10.0,
    minus_pct: float = 10.0,
    custom_kwh: float | None = None,
    peak_shift_pct: float = 10.0,
    peak_share_pct: float = 40.0,
) -> dict:
    """What-if scenarios for the household bill simulator.

    Returns the base bill plus +X% / -X% / custom-consumption bills, the bill
    difference between base and the largest scenario, and estimated savings
    from shifting peak usage to off-peak (time-of-use tariffs only).
    """
    base = compute_household_bill(monthly_consumption_kwh, tariff, peak_share_pct)
    plus = compute_household_bill(monthly_consumption_kwh * (1.0 + plus_pct / 100.0), tariff, peak_share_pct)
    minus = compute_household_bill(monthly_consumption_kwh * (1.0 - minus_pct / 100.0), tariff, peak_share_pct)

    custom = None
    if custom_kwh is not None:
        custom = compute_household_bill(custom_kwh, tariff, peak_share_pct)
        custom["change_pct"] = round(
            (custom["total"] - base["total"]) / base["total"] * 100.0, 2
        ) if base["total"] else 0.0

    # Estimated bill difference: base vs the largest change applied (custom if
    # given, otherwise +X%).
    target = custom if custom is not None else plus
    target_kwh = (custom or plus)["monthly_consumption_kwh"]
    bill_difference = {
        "from_consumption_kwh": base["monthly_consumption_kwh"],
        "to_consumption_kwh": target_kwh,
        "amount": round(target["total"] - base["total"], 2),
        "pct": round((target["total"] - base["total"]) / base["total"] * 100.0, 2)
        if base["total"] else 0.0,
    }

    estimated_savings = None
    if tariff.get("peak_hours") is not None:
        peak_rate = peak_rate_per_kwh(tariff)
        off_rate = off_peak_rate_per_kwh(tariff)
        peak_kwh = monthly_consumption_kwh * peak_share_pct / 100.0
        shifted_kwh = peak_kwh * peak_shift_pct / 100.0
        estimated_savings = {
            "applicable": True,
            "shift_pct": peak_shift_pct,
            "peak_kwh_in_bill": round(peak_kwh, 3),
            "shifted_kwh": round(shifted_kwh, 3),
            "peak_rate_per_kwh": peak_rate,
            "off_peak_rate_per_kwh": off_rate,
            "savings_per_month": round(shifted_kwh * (peak_rate - off_rate), 2),
            "assumption": (
                f"{peak_shift_pct:g}% of peak-period kWh ({shifted_kwh:,.1f} kWh) "
                "is hypothetically shifted from the peak to the off-peak tariff."
            ),
        }

    return {
        "scope": config.SCOPE_HOUSEHOLD,
        "scope_label": config.SCOPE_HOUSEHOLD_LABEL,
        "reporting_period": "1 month",
        "consumption_unit": "kWh",
        "energy_unit": "kWh",
        "tariff_unit": _tariff_unit(tariff),
        "base": base,
        "plus_10pct": {
            "consumption_kwh": plus["monthly_consumption_kwh"],
            "total": plus["total"],
            "change_pct": round((plus["total"] - base["total"]) / base["total"] * 100.0, 2)
            if base["total"] else 0.0,
        },
        "minus_10pct": {
            "consumption_kwh": minus["monthly_consumption_kwh"],
            "total": minus["total"],
            "change_pct": round((minus["total"] - base["total"]) / base["total"] * 100.0, 2)
            if base["total"] else 0.0,
        },
        "custom": custom,
        "bill_difference": bill_difference,
        "estimated_savings": estimated_savings,
    }


if __name__ == "__main__":
    sys.exit(0)
