"""Phase 6: independent manual verification of the December 2018 bill.

Recomputes the latest full-month bill from first principles, walking every
step in the open (hourly MW load -> MWh -> kWh -> tariff -> energy charge ->
fixed charge -> tax -> final bill -> peak-shift savings) and asserts that the
independently computed numbers match the persisted bill report.

The arithmetic here deliberately re-implements the tariff rules inline instead
of calling tariffs.compute_bill, so it is a genuine cross-check of the phase 6
engine rather than a re-run of the same code.

Usage:
    python ml/scripts/verify_bill_math.py [--tariff time_of_use]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("verify_bill_math")

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import config  # noqa: E402

_DECIMAL = 2


def rate_for_hour(t: dict, hour: int) -> float:
    """Peak/off-peak price per MWh at a given hour (inline re-implementation)."""
    peak = t.get("peak_hours")
    if peak is None:
        return float(t.get("off_peak_price_per_mwh", t.get("unit_price_per_mwh", 0.0)))
    if peak["start"] <= hour <= peak["end"]:
        if "peak_multiplier" in t:
            return float(t["unit_price_per_mwh"]) * float(t["peak_multiplier"])
        return float(t["unit_price_per_mwh"])
    return float(t.get("off_peak_price_per_mwh", t.get("unit_price_per_mwh", 0.0)))


def slab_charge(t: dict, energy_mwh: float) -> tuple[float, list[dict]]:
    """Marginal slab charge and per-slab breakdown (inline re-implementation)."""
    rows, remaining = [], energy_mwh
    for slab in t["slabs"]:
        lower = float(slab["min_mwh"])
        upper = float(slab["max_mwh"]) if slab.get("max_mwh") is not None else float("inf")
        price = float(slab["price_per_mwh"])
        taken = max(0.0, min(remaining, upper - lower))
        if taken > 0 or upper == float("inf"):
            rows.append(
                {
                    "min_mwh": lower,
                    "max_mwh": None if upper == float("inf") else upper,
                    "mwh": round(taken, _DECIMAL),
                    "price_per_mwh": price,
                    "charge": round(taken * price, _DECIMAL),
                }
            )
        remaining = max(0.0, remaining - taken)
        if remaining == 0:
            break
    return sum(r["charge"] for r in rows), rows


def last_full_month(series: pd.Series) -> pd.Series:
    """Slice the series to the latest complete calendar month."""
    period = pd.Period(series.index.max(), freq="M")
    return series[series.index.to_period("M") == period]


def independent_bill(series: pd.Series, t: dict) -> dict:
    """Recompute the bill from the hourly MW series step by step."""
    energy_mwh = round(float(series.sum()), _DECIMAL)
    energy_kwh = round(energy_mwh * config.KWH_PER_MWH, _DECIMAL)

    peak = t.get("peak_hours")
    peak_mwh = round(
        float(series[series.index.hour.map(lambda h: peak["start"] <= h <= peak["end"])].sum())
        if peak is not None else 0.0,
        _DECIMAL,
    )
    off_peak_mwh = round(energy_mwh - peak_mwh, _DECIMAL)

    if "slabs" in t:
        charge, slab_rows = slab_charge(t, energy_mwh)
    else:
        charge = round(
            sum(rate_for_hour(t, idx.hour) * v for idx, v in series.items()), _DECIMAL
        )
        slab_rows = []

    fixed = round(float(t.get("fixed_charge_per_month", 0.0)), _DECIMAL)
    additional = round(float(t.get("additional_charges", 0.0)), _DECIMAL)
    subtotal = round(charge + fixed + additional, _DECIMAL)
    taxes = round(subtotal * float(t.get("tax_pct", 0.0)) / 100.0, _DECIMAL)
    total = round(subtotal + taxes, _DECIMAL)

    return {
        "period": str(series.index.min().year) + "-" + str(series.index.min().month).zfill(2),
        "hours": int(len(series)),
        "energy_mwh": energy_mwh,
        "energy_kwh": energy_kwh,
        "peak_mwh": peak_mwh,
        "off_peak_mwh": off_peak_mwh,
        "energy_charge": charge,
        "slab_breakdown": slab_rows,
        "fixed_charge": fixed,
        "additional_charges": additional,
        "taxes": taxes,
        "total": total,
    }


def peak_shift_savings(series: pd.Series, t: dict, shift_pct: float) -> dict:
    """Estimated savings for this single period from hypothetically moving
    shift_pct% of its peak usage to off-peak (inline)."""
    peak = t.get("peak_hours")
    if peak is None or "off_peak_price_per_mwh" not in t:
        return {"applicable": False}
    period = str(series.index.min().to_period("M"))
    peak_mwh = float(series[series.index.hour.map(lambda h: peak["start"] <= h <= peak["end"])].sum())
    shifted_mwh = peak_mwh * shift_pct / 100.0
    peak_rate = rate_for_hour(t, peak["start"])
    off_rate = float(t["off_peak_price_per_mwh"])
    saving = round(shifted_mwh * (peak_rate - off_rate), _DECIMAL)
    return {
        "applicable": True,
        "period_label": period,
        "shift_pct": shift_pct,
        "assumption": (
            f"{shift_pct}% of {period} peak-period energy is hypothetically "
            "shifted from the peak tariff to the off-peak tariff."
        ),
        "peak_mwh_in_bill": round(peak_mwh, _DECIMAL),
        "shifted_mwh": round(shifted_mwh, _DECIMAL),
        "peak_rate_per_mwh": peak_rate,
        "off_peak_rate_per_mwh": off_rate,
        "estimated_savings": saving,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tariff", default=config.DEFAULT_TARIFF, help="tariff name")
    args = parser.parse_args()

    t = json.loads((config.TARIFFS_DIR / f"{args.tariff}.json").read_text(encoding="utf-8"))
    df = pd.read_parquet(config.FEATURES_DATA)
    df.index = pd.to_datetime(df.index)
    series = df[config.CLEANED_COLUMN].sort_index()

    month = last_full_month(series)
    bill = independent_bill(month, t)
    savings = peak_shift_savings(month, t, config.PEAK_SHIFT_PERCENT)

    log.info("== Independent bill verification for %s (tariff: %s) ==", bill["period"], t["name"])
    log.info("steps:")
    log.info("  1. hourly MW load  -> rows=%d, sum(MW)=%s %s", bill["hours"], f"{bill['energy_mwh']:,}", config.ENERGY_UNIT)
    log.info("  2. -> energy       = %s %s = %s kWh", f"{bill['energy_mwh']:,}", config.ENERGY_UNIT, f"{bill['energy_kwh']:,}")
    log.info("  3. applicable rates per %s: %s", config.ENERGY_UNIT, _describe_rates(t))
    log.info("  4. energy charge   = %s %s", f"{bill['energy_charge']:,}", config.CURRENCY_SYMBOL)
    log.info("  5. fixed charge    = %s %s", f"{bill['fixed_charge']:,}", config.CURRENCY_SYMBOL)
    log.info("  6. taxes (%s%%)      = %s %s", t.get("tax_pct", 0), f"{bill['taxes']:,}", config.CURRENCY_SYMBOL)
    log.info("  7. FINAL BILL      = %s %s", f"{bill['total']:,}", config.CURRENCY_SYMBOL)
    if savings.get("applicable"):
        month = pd.Period(savings["period_label"], freq="M").strftime("%B %Y")
        log.info("  8. estimated %s peak-shift savings = %s %s",
                 month, f"{savings['estimated_savings']:,}", config.CURRENCY_SYMBOL)
        log.info("     assumption: %s", savings["assumption"])

    report = json.loads(config.BILL_REPORT.read_text(encoding="utf-8"))
    if report["tariff"]["name"] != t["name"]:
        log.error("report tariff is %r, not %r. Rerun bill_engine with --tariff %s",
                  report["tariff"]["name"], t["name"], args.tariff)
        return 1
    cb = report["current_bill"]
    ws = report["what_if"]["peak_shift_savings"]

    checks = [
        ("energy_mwh", bill["energy_mwh"], cb["energy_mwh"]),
        ("energy_kwh", bill["energy_kwh"], cb["energy_kwh"]),
        ("peak_mwh", bill["peak_mwh"], cb["peak_mwh"]),
        ("off_peak_mwh", bill["off_peak_mwh"], cb["off_peak_mwh"]),
        ("energy_charge", bill["energy_charge"], cb["energy_charge"]),
        ("fixed_charge", bill["fixed_charge"], cb["fixed_charge"]),
        ("taxes", bill["taxes"], cb["taxes"]),
        ("total", bill["total"], cb["total"]),
    ]
    failures = 0
    for name, indep, reportv in checks:
        ok = abs(indep - reportv) < 0.01
        failures += 0 if ok else 1
        log.info("check %-16s independent=%-16s report=%-16s %s",
                 name, f"{indep:,}", f"{reportv:,}", "OK" if ok else "MISMATCH")

    if savings.get("applicable") and ws.get("applicable"):
        ok = abs(savings["estimated_savings"] - ws["estimated_savings"]) < 0.01
        failures += 0 if ok else 1
        log.info("check %-16s independent=%-16s report=%-16s %s",
                 "peak_shift_savings", f"{savings['estimated_savings']:,}",
                 f"{ws['estimated_savings']:,}", "OK" if ok else "MISMATCH")

    # The savings period must match the reporting period.
    if savings.get("applicable"):
        ok_period = savings["period_label"] == cb.get("period_label")
        failures += 0 if ok_period else 1
        log.info("check %-16s independent=%-10s report=%-10s %s",
                 "savings_period", savings.get("period_label"),
                 cb.get("period_label"), "OK" if ok_period else "MISMATCH")

    if failures:
        log.error("Verification FAILED: %d mismatched field(s) vs bill_report.json", failures)
        return 1
    log.info("Verification PASSED: independent bill matches bill_report.json.")
    return 0


def _describe_rates(t: dict) -> str:
    peak = t.get("peak_hours")
    if peak is None:
        if "slabs" in t:
            tiers = ", ".join(
                f"{s.get('min_mwh')}-{s.get('max_mwh') or '+'}:{s['price_per_mwh']}"
                for s in t["slabs"]
            )
            return f"slabs [{tiers}]"
        return f"{float(t.get('unit_price_per_mwh', 0.0)):,.2f}"
    rate = rate_for_hour(t, peak["start"])
    off = float(t.get("off_peak_price_per_mwh", t.get("unit_price_per_mwh", 0.0)))
    return f"peak {rate:,.2f} (h{peak['start']}-h{peak['end']}) / off-peak {off:,.2f}"


if __name__ == "__main__":
    sys.exit(main())