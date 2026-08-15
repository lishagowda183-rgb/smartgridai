"""Analytics routes: by-hour / by-day-of-week / by-month profiles + peak hours."""

from __future__ import annotations

from fastapi import APIRouter

from ...schemas import (
    AnalyticsHourlyResponse,
    AnalyticsMonthlyResponse,
    AnalyticsWeeklyResponse,
    HouseholdAnalyticsResponse,
    PeakHoursResponse,
    WeatherRelationshipResponse,
)
from ...services import analytics
from ...services import household_analytics

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/hourly", response_model=AnalyticsHourlyResponse, summary="Average consumption by hour of day")
def hourly() -> dict:
    return analytics.hourly()


@router.get("/weekly", response_model=AnalyticsWeeklyResponse, summary="Average consumption by day of week")
def weekly() -> dict:
    return analytics.weekly()


@router.get("/monthly", response_model=AnalyticsMonthlyResponse, summary="Average consumption by month of year")
def monthly() -> dict:
    return analytics.monthly()


@router.get("/peak-hours", response_model=PeakHoursResponse, summary="Peak-hour analysis (persisted report)")
def peak_hours() -> dict:
    return analytics.peak_hours()


@router.get(
    "/weather-relationship",
    response_model=WeatherRelationshipResponse,
    summary="Real weather-demand correlations + temperature buckets",
)
def weather_relationship() -> dict:
    return analytics.weather_relationship()


@router.get(
    "/household",
    response_model=HouseholdAnalyticsResponse,
    summary="Household analytics on the uploaded dataset (patterns, weather, anomalies)",
    responses={404: {"description": "No dataset uploaded yet (onboarding state)"}},
)
def household(dataset_id: str | None = None) -> dict:
    """Patterns (hour/day/month), monthly trend, peak hours, distribution,
    weather-consumption correlations (only when real weather overlaps) and
    rolling-z anomalies — all from the uploaded data only."""
    return household_analytics.analytics(dataset_id)