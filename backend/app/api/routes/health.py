"""Health and meta endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ... import config as api_config
from ...services import cache
from ...schemas import HealthResponse

router = APIRouter(tags=["health"])

APP_NAME = "SmartGridAI API"
APP_VERSION = "1.0.0"


@router.get("/health", response_model=HealthResponse, summary="Service health")
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app=APP_NAME,
        version=APP_VERSION,
        prefix=api_config.API_PREFIX,
        docs="/docs",
        redoc="/redoc",
        timestamp=cache.utc_now(),
    )