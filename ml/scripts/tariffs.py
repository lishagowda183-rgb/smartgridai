"""Phase 6: electricity tariff model and deterministic bill calculation.

Tariffs are fully described in ml/tariffs/*.json (never hard-coded here).
Supported tariff constructs:

  * per-unit rate            -> unit_price_per_mwh
  * slab-based pricing       -> slabs: [{min_mwh, max_mwh|None, price_per_mwh}]
  * fixed charges            -> fixed_charge_per_month
  * taxes / additional       -> tax_pct (percentage) + additional_charges (flat)
  * peak/off-peak rates      -> peak_hours + either peak_multiplier (applied on
                                top of unit_price_per_mwh) or an explicit
                                off_peak_price_per_mwh

``compute_bill`` performs all arithmetic in plain Python (deterministic, no LLM)
and returns an itemized bill. Everything here is pure and unit-testable.
"""

from __future__ import annotations

import json
import logging
import sys

import numpy as np
import pandas as pd

import config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("tariffs")


# ---------------------------------------------------------------------------
# Tariff schema + loading
# ---------------------------------------------------------------------------
class TariffValidationError(ValueError):
    """Raised when a tariff file violates the expected schema."""


def validate_tariff(t: dict) -> dict:
    """Validate a tariff dict against the supported schema."""
    if not isinstance(t, dict):
        raise TariffValidationError("tariff must be a JSON object")
    name = t.get("name")
    if not isinstance(name, str) or not name.strip():
        raise TariffValidationError("tariff requires a non-empty string 'name'")

    has_unit = isinstance(t.get("unit_price_per_mwh"), (int, float))
    slabs = t.get("slabs")
    has_slabs = isinstance(slabs, list) and len(slabs) > 0
    if not (has_unit or has_slabs):
        raise TariffValidationError(
            "tariff requires 'unit_price_per_mwh' or a non-empty 'slabs' list"
        )
    if has_unit and not has_slabs and t.get("unit_price_per_mwh") < 0:
        raise TariffValidationError("'unit_price_per_mwh' cannot be negative")

    if has_slabs:
        for i, slab in enumerate(slabs):
            if not isinstance(slab, dict):
                raise TariffValidationError(f"slab[{i}] must be an object")
            if "min_mwh" not in slab or "price_per_mwh" not in slab:
                raise TariffValidationError(
                    f"slab[{i}] requires 'min_mwh' and 'price_per_mwh'"
                )
            if slab.get("price_per_mwh", 0) < 0:
                raise TariffValidationError(f"slab[{i}] price cannot be negative")

    for key in ("fixed_charge_per_month", "tax_pct", "additional_charges"):
        val = t.get(key, 0.0)
        if not isinstance(val, (int, float)) or val < 0:
            raise TariffValidationError(f"'{key}' must be a non-negative number")

    peak = t.get("peak_hours")
    if peak is not None:
        if not isinstance(peak, dict) or "start" not in peak or "end" not in peak:
            raise TariffValidationError("'peak_hours' requires 'start' and 'end'")
        start, end = peak["start"], peak["end"]
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start <= end <= 23:
            raise TariffValidationError("'peak_hours' start/end must be hours in 0..23")

    if "peak_multiplier" in t:
        if not isinstance(t["peak_multiplier"], (int, float)) or t["peak_multiplier"] <= 0:
            raise TariffValidationError("'peak_multiplier' must be a positive number")
    if "off_peak_price_per_mwh" in t:
        if not isinstance(t["off_peak_price_per_mwh"], (int, float)) or t["off_peak_price_per_mwh"] < 0:
            raise TariffValidationError("'off_peak_price_per_mwh' cannot be negative")

    allowed = {
        "name", "display_name", "currency", "unit_price_per_mwh", "slabs",
        "fixed_charge_per_month", "tax_pct", "additional_charges", "peak_hours",
        "peak_multiplier", "off_peak_price_per_mwh", "billing_cycle",
    }
    unknown = set(t) - allowed
    if unknown:
        raise TariffValidationError(f"unknown tariff keys: {sorted(unknown)}")
    return t


def tariff_paths() -> list:
    """Sorted list of tariff files in the configured tariffs directory."""
    if not config.TARIFFS_DIR.is_dir():
        raise FileNotFoundError(f"tariffs directory missing: {config.TARIFFS_DIR}")
    return sorted(config.TARIFFS_DIR.glob("*.json"))


def available_tariffs() -> list[str]:
    """Names of every tariff defined in ml/tariffs/."""
    names = []
    for path in tariff_paths():
        try:
            names.append(json.loads(path.read_text(encoding="utf-8"))["name"])
        except (json.JSONDecodeError, KeyError):
            continue
    return names


def load_tariff(name: str | None = None) -> dict:
    """Load + validate a tariff by name (defaults to config.DEFAULT_TARIFF)."""
    selection = name or config.DEFAULT_TARIFF
    for path in tariff_paths():
        t = json.loads(path.read_text(encoding="utf-8"))
        if t.get("name") == selection:
            return validate_tariff(t)
    raise TariffValidationError(
        f"unknown tariff '{selection}'. Available: {available_tariffs()}"
    )


# ---------------------------------------------------------------------------
# Pricing helpers
# ---------------------------------------------------------------------------
def unit_price(t: dict) -> float:
    """Effective price per MWh (off-peak or base) for the tariff."""
    if "off_peak_price_per_mwh" in t:
        return float(t["off_peak_price_per_mwh"])
    return float(t.get("unit_price_per_mwh", 0.0))


def rate_for_hour(t: dict, hour: int) -> float:
    """Price per MWh at a given hour (handles peak/off-peak)."""
    peak = t.get("peak_hours")
    if peak is None:
        return unit_price(t)
    if peak["start"] <= hour <= peak["end"]:
        if "peak_multiplier" in t:
            return float(t["unit_price_per_mwh"]) * float(t["peak_multiplier"])
        return float(t["unit_price_per_mwh"])
    return unit_price(t)


def slab_price_per_mwh(t: dict, energy_mwh: float) -> float:
    """Price per MWh under slab pricing (first matching slab)."""
    for slab in t["slabs"]:
        if energy_mwh >= slab["min_mwh"] and (
            slab.get("max_mwh") is None or energy_mwh < slab["max_mwh"]
        ):
            return float(slab["price_per_mwh"])
    return float(t["slabs"][-1]["price_per_mwh"])


def in_peak_hour(t: dict, hour: int) -> bool:
    peak = t.get("peak_hours")
    return bool(peak and peak["start"] <= hour <= peak["end"])


# ---------------------------------------------------------------------------
# Bill calculation (all arithmetic in code)
# ---------------------------------------------------------------------------
def split_peak_offpeak(t: dict, series: pd.Series) -> tuple[float, float]:
    """Return (peak MWh, off-peak MWh) for the series under the tariff."""
    if t.get("peak_hours") is None:
        return 0.0, float(series.sum())
    hours = series.index.hour.values
    peak_mask = (hours >= t["peak_hours"]["start"]) & (hours <= t["peak_hours"]["end"])
    peak = float(series.values[peak_mask].sum())
    return peak, float(series.sum()) - peak


def slab_breakdown(t: dict, energy_mwh: float) -> list[dict]:
    """Marginal slab breakdown: how many MWh fall into each tier."""
    if "slabs" not in t:
        return []
    rows = []
    remaining = energy_mwh
    for slab in t["slabs"]:
        lower, price = float(slab["min_mwh"]), float(slab["price_per_mwh"])
        upper = float(slab["max_mwh"]) if slab.get("max_mwh") is not None else np.inf
        taken = max(0.0, min(remaining, upper - lower))
        if taken > 0 or upper == np.inf:
            rows.append(
                {
                    "min_mwh": lower,
                    "max_mwh": None if upper == np.inf else upper,
                    "mwh": round(taken, 3),
                    "price_per_mwh": price,
                    "charge": round(taken * price, 2),
                }
            )
        remaining = max(0.0, remaining - taken)
        if remaining == 0:
            break
    return rows


def sanity_notes(t: dict, series: pd.Series) -> list[str]:
    """Warnings about the scale of the consumption series vs the tariff.

    The raw dataset is regional grid load (MW/hour), so a month sums to tens
    of thousands of MWh — far beyond any household meter. This is expected for
    this dataset's scope and the bill amounts are correct for that scope; the
    notes make the scale explicit instead of silently presenting grid-scale
    totals as though they were a household bill.
    """
    notes: list[str] = []
    if series.empty:
        return notes
    energy_mwh = float(series.sum())
    scope = config.DATA_SCOPE
    if "regional grid" in scope.lower() and energy_mwh > 100_000:
        notes.append(
            "Series is regional-grid load (hourly MW), not a household meter: "
            f"monthly energy of {energy_mwh:,.0f} {config.ENERGY_UNIT} reflects "
            "the whole region, and the resulting bill is a regional analytical "
            "estimate, not a household electricity bill."
        )
    return notes


def compute_bill(series: pd.Series, t: dict) -> dict:
    """Compute an itemized bill for hourly consumption over the series period.

    Returns: energy_mwh (and energy_kwh := MWh * KWH_PER_MWH), peak/off-peak
    split, energy_charge (with slab breakdown when applicable), fixed_charge,
    taxes (as % of subtotal), additional_charges, sanity notes and the final
    total.
    """
    series = series.dropna()
    energy_mwh = float(series.sum())
    peak_mwh, off_peak_mwh = split_peak_offpeak(t, series)

    if "slabs" in t:
        charge = sum(float(s["charge"]) for s in slab_breakdown(t, energy_mwh))
        slab_rows = slab_breakdown(t, energy_mwh)
    else:
        charge = sum(
            rate_for_hour(t, int(series.index[k].hour)) * series.values[k]
            for k in range(len(series))
        )
        slab_rows = []

    fixed = float(t.get("fixed_charge_per_month", 0.0))
    additional = float(t.get("additional_charges", 0.0))
    subtotal = charge + fixed + additional
    taxes = round(subtotal * float(t.get("tax_pct", 0.0)) / 100.0, 2)

    tariff_unit = f"{t.get('currency', config.CURRENCY_SYMBOL)}/MWh"
    period_label = (
        str(series.index.min().to_period("M")) if len(series) else None
    )

    return {
        "scope": config.SCOPE_REGIONAL_GRID,
        "scope_label": config.SCOPE_REGIONAL_LABEL,
        "reporting_period": period_label,
        "consumption_unit": config.CONSUMPTION_UNIT,
        "energy_unit": config.ENERGY_UNIT,
        "tariff_unit": tariff_unit,
        "period_start": str(series.index.min()),
        "period_end": str(series.index.max()),
        "hours": int(len(series)),
        "energy_mwh": round(energy_mwh, 3),
        "energy_kwh": round(energy_mwh * config.KWH_PER_MWH, 3),
        "peak_mwh": round(peak_mwh, 3),
        "off_peak_mwh": round(off_peak_mwh, 3),
        "energy_charge": round(charge, 2),
        "slab_breakdown": slab_rows,
        "peak_charge": round(peak_mwh * rate_for_hour(t, t.get("peak_hours", {}).get("start", 0)) if t.get("peak_hours") else 0.0, 2),
        "off_peak_charge": round(off_peak_mwh * unit_price(t), 2),
        "fixed_charge": round(fixed, 2),
        "additional_charges": round(additional, 2),
        "tax_pct": float(t.get("tax_pct", 0.0)),
        "taxes": taxes,
        "sanity_notes": sanity_notes(t, series),
        "total": round(subtotal + taxes, 2),
    }


def compute_monthly_bills(series: pd.Series, t: dict) -> pd.DataFrame:
    """Per-month bills across the whole series (one row per calendar month)."""
    rows = []
    for _, chunk in series.resample("ME"):
        if chunk.empty:
            continue
        bill = compute_bill(chunk, t)
        rows.append(
            {
                "period": str(chunk.index.min().strftime("%Y-%m")),
                "energy_mwh": bill["energy_mwh"],
                "total": bill["total"],
            }
        )
    return pd.DataFrame(rows)


def percentage_change(old: float, new: float) -> float:
    """Percent increase/decrease from old to new (None-safe -> 0.0)."""
    if not old:
        return 0.0
    return round((new - old) / old * 100.0, 2)


if __name__ == "__main__":
    sys.exit(0)