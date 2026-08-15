"""Bills service: regional grid (two-mode: cached report + recompute) and household."""

from __future__ import annotations

import logging

import config as ml_config

from .. import config as api_config
from ..errors import NotFoundError
from . import cache

log = logging.getLogger("api.bills")


# ---------------------------------------------------------------------------
# Regional Grid Energy Cost
# ---------------------------------------------------------------------------
def regional_tariffs() -> list[str]:
    import tariffs

    return tariffs.available_tariffs()


def regional_bill(tariff: str | None, horizon: str, recompute: bool = False) -> dict:
    """Regional grid bill report.

    Default: serve the persisted ``bill_report.json``. Pass ``recompute=true``
    (or different tariff/horizon params) to regenerate the report through
    ``bill_engine.build_report`` (slow: runs an iterated forecast).
    """
    import tariffs
    import bill_engine

    chosen_tariff = tariff or api_config.API_DEFAULT_TARIFF
    chosen_horizon = horizon or api_config.API_DEFAULT_HORIZON

    available = tariffs.available_tariffs()
    if chosen_tariff not in available:
        raise NotFoundError(f"unknown tariff '{chosen_tariff}'. Available: {available}")

    if not recompute and ml_config.BILL_REPORT.exists():
        cached = cache.load_bill_report()
        if not tariff and not horizon:
            return _tag(cached, served_from="cache")
        # Params provided: honor them by regenerating so the report matches them.
        return _tag(_rebuild(chosen_tariff, chosen_horizon), served_from="recomputed")

    report = _rebuild(chosen_tariff, chosen_horizon)
    return _tag(report, served_from="recomputed")


def _tag(report: dict, served_from: str) -> dict:
    report["_served_from"] = served_from
    report["_generated_at_api"] = cache.utc_now()
    return report


def _rebuild(tariff: str, horizon: str) -> dict:
    import bill_engine

    log.info("rebuilding regional bill report (tariff=%s horizon=%s)", tariff, horizon)
    report = bill_engine.build_report(tariff, horizon)
    cache.invalidate_report_cache(ml_config.BILL_REPORT)
    return report


# ---------------------------------------------------------------------------
# Household Bill Simulator (fully separate, per-kWh)
# ---------------------------------------------------------------------------
def household_tariffs() -> list[dict]:
    import household_bills as hb

    return hb.list_household_tariffs()


def household_tariff_names() -> list[str]:
    import household_bills as hb

    return hb.available_household_tariffs()


def household_calculate(monthly_kwh: float, tariff: str | None, peak_share_pct: float) -> dict:
    import household_bills as hb

    _require_household_tariff(tariff)
    t = hb.load_household_tariff(tariff)
    return hb.compute_household_bill(monthly_kwh, t, peak_share_pct)


def household_what_if(
    monthly_kwh: float,
    tariff: str | None,
    plus_pct: float,
    minus_pct: float,
    custom_kwh: float | None,
    peak_share_pct: float,
    peak_shift_pct: float,
) -> dict:
    import household_bills as hb

    _require_household_tariff(tariff)
    t = hb.load_household_tariff(tariff)
    return hb.household_what_if(
        monthly_kwh,
        t,
        plus_pct=plus_pct,
        minus_pct=minus_pct,
        custom_kwh=custom_kwh,
        peak_shift_pct=peak_shift_pct,
        peak_share_pct=peak_share_pct,
    )


def _require_household_tariff(name: str | None) -> None:
    import household_bills as hb

    avail = hb.available_household_tariffs()
    selection = name or "household_slabs"
    if selection not in avail:
        raise NotFoundError(f"unknown household tariff '{selection}'. Available: {avail}")