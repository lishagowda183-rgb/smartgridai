"""Bill routes: regional grid (two-mode) + household simulator."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ... import config as api_config
from ...schemas import (
    HouseholdBillResponse,
    HouseholdCalculateRequest,
    HouseholdWhatIfRequest,
    HouseholdWhatIfResponse,
    RegionalBillResponse,
    TariffListResponse,
)
from ...services import bills

router = APIRouter(prefix="/bills", tags=["bills"])


# --- Regional Grid Energy Cost (per-MWh, regional-scale) ----------------------
@router.get(
    "/regional/tariffs",
    response_model=TariffListResponse,
    summary="Available regional tariffs",
)
def regional_tariffs() -> dict:
    return {"tariffs": bills.regional_tariffs()}


@router.get(
    "/regional",
    response_model=RegionalBillResponse,
    summary="Regional grid bill report (cached; ?recompute=true to regenerate)",
)
def regional(
    tariff: str | None = Query(None, description="Tariff name (default time_of_use)"),
    horizon: str | None = Query(None, description="Forecast horizon e.g. 1m"),
    recompute: bool = Query(False, description="Regenerate the report instead of serving the cache"),
) -> dict:
    return bills.regional_bill(tariff=tariff, horizon=horizon, recompute=recompute)


# --- Household Bill Simulator (per-kWh, fully separate mode) ------------------
@router.get(
    "/household/tariffs",
    response_model=TariffListResponse,
    summary="Available household tariffs",
)
def household_tariffs() -> dict:
    return {"tariffs": bills.household_tariff_names()}


@router.post(
    "/household/calculate",
    response_model=HouseholdBillResponse,
    summary="Calculate a household bill for a monthly kWh figure",
)
def household_calculate(body: HouseholdCalculateRequest) -> dict:
    return bills.household_calculate(
        monthly_kwh=body.monthly_kwh,
        tariff=body.tariff,
        peak_share_pct=body.peak_share_pct,
    )


@router.post(
    "/household/what-if",
    response_model=HouseholdWhatIfResponse,
    summary="Household what-if scenarios (+/-%, custom kWh, peak-shift savings)",
)
def household_what_if(body: HouseholdWhatIfRequest) -> dict:
    return bills.household_what_if(
        monthly_kwh=body.monthly_kwh,
        tariff=body.tariff,
        plus_pct=body.plus_pct,
        minus_pct=body.minus_pct,
        custom_kwh=body.custom_kwh,
        peak_share_pct=body.peak_share_pct,
        peak_shift_pct=body.peak_shift_pct,
    )