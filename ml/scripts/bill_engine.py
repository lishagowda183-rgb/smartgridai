"""Phase 6: electricity bill and tariff engine.

Builds on the tariff model (ml/scripts/tariffs.py) to produce a full billing
report for the hourly consumption series:

  * current bill          -> latest full calendar month
  * historical bills      -> every calendar month across the series
  * forecasted bill       -> iterated multi-step forecast (reusing Phase 5's
                             iterated_forecast) priced through the tariff for
                             an arbitrary user horizon
  * monthly estimated     -> projection over MONTHLY_ESTIMATE_HOURS
  * bill comparison       -> current vs previous month and year-over-year,
                             with percentage increase/decrease
  * what-if               -> consumption +/-X%, and peak-to-off-peak shift
                             savings under a time-of-use tariff

All monetary arithmetic is delegated to tariffs.compute_bill (deterministic).
Horizons are given as strings like "2d", "30d", "1m", "2m", "1y".
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone

import joblib
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import config  # noqa: E402
import forecasting  # noqa: E402
import tariffs  # noqa: E402
from peak_hours import iterated_forecast  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("bill_engine")

# Regex for horizon strings: <number><unit> where unit in (d, m, y).
_HORIZON_RE = re.compile(r"^(\d+)([dmy])$")


def resolve_horizon(spec: str) -> int:
    """Convert a horizon string to hours. Units: d=days, m=months(30d), y=years(365d)."""
    m = _HORIZON_RE.match(spec.strip().lower())
    if not m:
        raise ValueError(
            f"invalid horizon '{spec}'. Use e.g. '2d', '30d', '1m', '2m', '1y'."
        )
    value, unit = int(m.group(1)), m.group(2)
    if unit == "d":
        return value * 24
    if unit == "m":
        return value * 30 * 24
    return value * 365 * 24


def style(amount: float) -> str:
    """Format a monetary amount with the configured currency."""
    return f"{config.CURRENCY_SYMBOL} {amount:,.2f}"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_series() -> pd.Series:
    """Hourly consumption series (100% coverage, sorted)."""
    df = forecasting.load_features()
    series = df[config.CLEANED_COLUMN]
    series.index = pd.to_datetime(series.index)
    return series.sort_index()


def last_full_month(series: pd.Series) -> pd.Period:
    """Period of the latest complete calendar month in the series."""
    months = sorted(series.resample("ME").groups)
    return pd.Period(months[-1], freq="M")


def month_range(series: pd.Series, period: pd.Period) -> pd.Series:
    """Slice the series to the exact calendar month of `period`."""
    mask = series.index.to_period("M") == period
    return series[mask]


# ---------------------------------------------------------------------------
# Bill computations
# ---------------------------------------------------------------------------
def current_bill(series: pd.Series, t: dict) -> dict:
    """Bill for the latest full calendar month."""
    period = last_full_month(series)
    month = month_range(series, period)
    bill = tariffs.compute_bill(month, t)
    bill["period_label"] = str(period)
    return bill


def previous_month_bill(series: pd.Series, t: dict) -> dict:
    """Bill for the calendar month before the latest full one (None-safe)."""
    months = sorted(series.resample("ME").groups)
    if len(months) < 2:
        return {}
    prev = pd.Period(months[-2], freq="M")
    month = month_range(series, prev)
    bill = tariffs.compute_bill(month, t)
    bill["period_label"] = str(prev)
    return bill


def year_ago_month_bill(series: pd.Series, t: dict) -> dict:
    """Bill for the same month one year earlier (None-safe)."""
    current = last_full_month(series)
    target = current - 12
    month = month_range(series, target)
    if month.empty:
        return {}
    bill = tariffs.compute_bill(month, t)
    bill["period_label"] = str(target)
    return bill


def historical_bills(series: pd.Series, t: dict) -> pd.DataFrame:
    """Per-month bills across the whole series."""
    return tariffs.compute_monthly_bills(series, t)


def forecasted_bill(t: dict, horizon_spec: str) -> dict:
    """Iterated forecast priced through the tariff for a user horizon."""
    model = joblib.load(config.PEAK_FORECAST_MODEL)
    series = load_series()
    hours = resolve_horizon(horizon_spec)
    forecast = iterated_forecast(series, model, days=hours // 24)
    bill = tariffs.compute_bill(forecast, t)
    bill["period_label"] = f"forecast {horizon_spec}"
    bill["horizon"] = horizon_spec
    bill["horizon_hours"] = hours
    return bill


def monthly_estimated_bill(t: dict) -> dict:
    """Estimated bill for the next MONTHLY_ESTIMATE_HOURS via the forecast."""
    model = joblib.load(config.PEAK_FORECAST_MODEL)
    series = load_series()
    hours = config.MONTHLY_ESTIMATE_HOURS
    forecast = iterated_forecast(series, model, days=hours // 24)
    bill = tariffs.compute_bill(forecast, t)
    bill["period_label"] = f"estimated_next_{hours // 24}d"
    bill["horizon_hours"] = hours
    return bill


def what_if_consumption(series: pd.Series, t: dict, pct: float) -> dict:
    """Bill for the current full month with consumption scaled by `pct` %."""
    period = last_full_month(series)
    month = month_range(series, period)
    scaled = month * (1.0 + pct / 100.0)
    return tariffs.compute_bill(scaled, t)


def peak_shift_savings(series: pd.Series, t: dict, shift_pct: float = config.PEAK_SHIFT_PERCENT) -> dict:
    """Estimated savings for the latest full month from hypothetically moving
    `shift_pct`% of that month's peak-hour usage to off-peak hours.

    NOTE: this is a single-period estimate tied to ``period_label``. It is NOT
    a monthly-recurring guarantee; the exact amount will differ month to month
    (see ``peak_shift_savings_by_month`` for per-month figures).
    """
    if t.get("peak_hours") is None or "off_peak_price_per_mwh" not in t:
        return {"applicable": False, "message": "tariff has no peak/off-peak rates"}
    period = last_full_month(series)
    month = month_range(series, period)

    hours = month.index.hour.values
    peak_mask = (hours >= t["peak_hours"]["start"]) & (hours <= t["peak_hours"]["end"])
    peak_mwh = float(month.values[peak_mask].sum())
    shifted_mwh = peak_mwh * shift_pct / 100.0

    # Marginal saving per MWh moved: peak rate - off-peak rate.
    peak_rate = tariffs.rate_for_hour(t, t["peak_hours"]["start"])
    off_rate = float(t["off_peak_price_per_mwh"])
    saving = shifted_mwh * (peak_rate - off_rate)

    base = current_bill(series, t)
    return {
        "applicable": True,
        "period_label": str(period),
        "shift_pct": shift_pct,
        "assumption": (
            f"{shift_pct}% of {period} peak-period energy is hypothetically "
            "shifted from the peak tariff to the off-peak tariff."
        ),
        "peak_mwh_in_bill": round(peak_mwh, 3),
        "shifted_mwh": round(shifted_mwh, 3),
        "peak_rate_per_mwh": peak_rate,
        "off_peak_rate_per_mwh": off_rate,
        "estimated_savings": round(saving, 2),
        "estimated_savings_pct": tariffs.percentage_change(base["total"], base["total"] - saving),
        "new_estimated_total": round(base["total"] - saving, 2),
    }


def peak_shift_savings_by_month(
    series: pd.Series, t: dict, shift_pct: float = config.PEAK_SHIFT_PERCENT
) -> list[dict]:
    """Per-calendar-month peak-shift savings, each labeled with its own month.

    Same hypothetical as ``peak_shift_savings`` but computed independently for
    every month in the series, so each figure is explicitly a single-period
    estimate for that specific month rather than a running monthly amount.
    """
    peak = t.get("peak_hours")
    if peak is None or "off_peak_price_per_mwh" not in t:
        return []
    peaks = np.asarray(
        [peak["start"] <= h <= peak["end"] for h in range(24)]
    )
    peak_rate = tariffs.rate_for_hour(t, peak["start"])
    off_rate = float(t["off_peak_price_per_mwh"])

    rows: list[dict] = []
    for _, chunk in series.resample("ME"):
        if chunk.empty:
            continue
        per_hour = np.bincount(chunk.index.hour.values, weights=chunk.values, minlength=24)
        peak_mwh = float(per_hour[peaks].sum())
        shifted_mwh = peak_mwh * shift_pct / 100.0
        rows.append(
            {
                "period_label": str(chunk.index.min().to_period("M")),
                "shift_pct": shift_pct,
                "assumption": (
                    f"{shift_pct}% of {str(chunk.index.min().to_period('M'))} "
                    "peak-period energy is hypothetically shifted from the "
                    "peak tariff to the off-peak tariff."
                ),
                "peak_mwh_in_bill": round(peak_mwh, 3),
                "shifted_mwh": round(shifted_mwh, 3),
                "peak_rate_per_mwh": peak_rate,
                "off_peak_rate_per_mwh": off_rate,
                "estimated_savings": round(shifted_mwh * (peak_rate - off_rate), 2),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Report + plot
# ---------------------------------------------------------------------------
def build_report(tariff_name: str | None, horizon: str) -> dict:
    """Assemble the full billing report and persist artifacts."""
    config.ensure_dirs()
    t = tariffs.load_tariff(tariff_name)
    series = load_series()

    current = current_bill(series, t)
    previous = previous_month_bill(series, t)
    year_ago = year_ago_month_bill(series, t)
    history = historical_bills(series, t)
    forecast = forecasted_bill(t, horizon)
    estimated = monthly_estimated_bill(t)

    what10 = what_if_consumption(series, t, 10.0)
    whatm10 = what_if_consumption(series, t, -10.0)
    savings = peak_shift_savings(series, t)
    savings_by_month = peak_shift_savings_by_month(series, t)

    comparison = {
        "current_month": current.get("period_label"),
        "previous_month": previous.get("period_label", None),
        "previous_month_total": previous.get("total"),
        "current_month_total": current["total"],
        "change_vs_previous_pct": tariffs.percentage_change(
            previous.get("total"), current["total"]
        ),
        "year_ago_month": year_ago.get("period_label", None),
        "year_ago_total": year_ago.get("total"),
        "change_yoy_pct": tariffs.percentage_change(
            year_ago.get("total"), current["total"]
        ),
    }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "currency": config.CURRENCY_SYMBOL,
        "mode": config.SCOPE_REGIONAL_GRID,
        "units": {
            "scope": config.SCOPE_REGIONAL_GRID,
            "scope_label": config.SCOPE_REGIONAL_LABEL,
            "consumption_unit": config.CONSUMPTION_UNIT,
            "energy_unit": config.ENERGY_UNIT,
            "kwh_per_mwh": config.KWH_PER_MWH,
            "tariff_unit": f"{t.get('currency', config.CURRENCY_SYMBOL)}/MWh",
            "note": (
                "Hourly regional-grid load (MW) summed to MWh over the billing "
                "period. Bills are regional-scale analytical estimates of grid "
                "energy cost, NOT household electricity bills."
            ),
        },
        "sanity_notes": current.get("sanity_notes", []),
        "tariff": t,
        "horizon": horizon,
        "current_bill": current,
        "previous_month_bill": previous or None,
        "year_ago_bill": year_ago or None,
        "comparison": comparison,
        "monthly_estimated_bill": estimated,
        "forecasted_bill": forecast,
        "what_if": {
            "consume_plus_10pct": {
                "total": what10["total"],
                "change_pct": tariffs.percentage_change(current["total"], what10["total"]),
            },
            "consume_minus_10pct": {
                "total": whatm10["total"],
                "change_pct": tariffs.percentage_change(current["total"], whatm10["total"]),
            },
            "peak_shift_savings": savings,
            "peak_shift_savings_by_month": savings_by_month,
        },
        "historical_bill_count": int(len(history)),
    }

    config.BILL_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("Bill report written to %s", config.BILL_REPORT)

    if savings_by_month:
        pd.DataFrame(savings_by_month).to_csv(config.PEAK_SHIFT_SAVINGS_CSV, index=False)
        log.info("Per-month peak-shift savings written to %s", config.PEAK_SHIFT_SAVINGS_CSV)

    history.to_csv(config.BILL_HISTORY_CSV, index=False)
    log.info("Bill history written to %s", config.BILL_HISTORY_CSV)
    build_history_plot(history, t)
    return report


def build_history_plot(history: pd.DataFrame, t: dict) -> None:
    """Bar chart of the monthly bill totals."""
    fig, ax = plt.subplots(figsize=(14, 5.5))
    x = np.arange(len(history))
    ax.bar(x, history["total"], color="#4c78a8", width=0.75)
    ax.set_title(f"Monthly bill ({t.get('display_name', t['name'])}) — {config.CURRENCY_SYMBOL}")
    ax.set_xlabel("Month")
    ax.set_ylabel(f"Bill total ({config.CURRENCY_SYMBOL})")
    ax.grid(axis="y", alpha=0.3)
    step = max(1, len(history) // 12)
    ticks = list(range(0, len(history), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([history["period"].iloc[i] for i in ticks], rotation=45, fontsize=8)
    fig.tight_layout()
    fig.savefig(config.BILL_HISTORY_PLOT, dpi=130)
    plt.close(fig)
    log.info("Bill history plot written to %s", config.BILL_HISTORY_PLOT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tariff", default=None, help="tariff name (from ml/tariffs/)")
    parser.add_argument("--horizon", default="1m", help="forecast horizon: 2d/30d/1m/2m/1y")
    parser.add_argument("--currency", default=None, help="override CURRENCY_SYMBOL")
    args = parser.parse_args()

    if args.currency:
        import os

        os.environ["CURRENCY_SYMBOL"] = args.currency

    try:
        report = build_report(args.tariff, args.horizon)
        current = report["current_bill"]
        log.info("Tariff: %s | current bill %s (%s)", t_name(report), style(current["total"]), current["period_label"])
        comp = report["comparison"]
        log.info("vs previous: %+.2f%% | YoY: %+.2f%%", comp["change_vs_previous_pct"], comp["change_yoy_pct"])
        if report["what_if"]["peak_shift_savings"].get("applicable"):
            ps = report["what_if"]["peak_shift_savings"]
            month_label = pd.Period(ps["period_label"], freq="M").strftime("%B %Y")
            log.info("Estimated %s peak-shift savings: %s", month_label, style(ps["estimated_savings"]))
            log.info("Assumption: %s", ps["assumption"])
    except Exception as exc:
        log.error("%s", exc)
        return 1
    return 0


def t_name(report: dict) -> str:
    return report["tariff"].get("display_name", report["tariff"]["name"])


if __name__ == "__main__":
    sys.exit(main())