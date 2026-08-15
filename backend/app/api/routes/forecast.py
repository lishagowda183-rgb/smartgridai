"""Forecast routes (iterated multi-step forecast from the trained model)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ... import config as api_config
from ...schemas import ForecastDailyResponse, ForecastHourlyResponse, ForecastMonthlyResponse
from ...services import forecast

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/hourly", response_model=ForecastHourlyResponse, summary="Hourly forecast (MW)")
def hourly(
    hours: int = Query(24, description="Horizon in hours"),  # validated in service
) -> dict:
    if hours not in api_config.ALLOWED_FORECAST_HOURS:
        raise ValueError(f"hours must be one of {api_config.ALLOWED_FORECAST_HOURS}")
    return forecast.hourly(hours)


@router.get("/daily", response_model=ForecastDailyResponse, summary="Daily forecast (mean MW + energy MWh)")
def daily(
    days: int = Query(7, ge=1, le=api_config.MAX_FORECAST_DAYS),
) -> dict:
    return forecast.daily(days)


@router.get("/monthly", response_model=ForecastMonthlyResponse, summary="Monthly forecast (mean MW + energy MWh)")
def monthly(
    months: int = Query(1, ge=1, le=12)
) -> dict:
    return forecast.monthly(months)