"""Weather routes (read-only, persisted Open-Meteo artifact)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ...schemas import WeatherCurrentResponse, WeatherForecastResponse
from ...services import weather

router = APIRouter(prefix="/weather", tags=["weather"])


@router.get("/current", response_model=WeatherCurrentResponse, summary="Current weather observation")
def current() -> dict:
    return weather.current()


@router.get("/forecast", response_model=WeatherForecastResponse, summary="Hourly weather forecast")
def forecast(
    days: int = Query(7, ge=1, le=30),
) -> dict:
    return weather.forecast(days)