"""FastAPI application for SmartGridAI Phase 7.

Wires CORS, logging, structured error handlers, the versioned API router and
the automatic OpenAPI docs (/docs, /redoc). Exposes the Phase 1-6 pipeline
through ``/api/v1`` endpoints without calling any external service.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config as api_config
from .api.routes import (
    agent,
    analytics,
    anomalies,
    bills,
    consumption,
    forecast,
    forecast_user,
    health,
    weather,
)
from .errors import APIError

log = logging.getLogger("api")

APP_NAME = "SmartGridAI API"
APP_VERSION = "1.0.0"
APP_DESCRIPTION = (
    "SmartGridAI – Weather-Aware Household Electricity Consumption Forecasting "
    "& AI Energy Assistant. Forecasts and analytics run ONLY on your uploaded "
    "consumption (CSV/XLSX, kWh). Short-term forecasts are weather-aware when "
    "real future weather overlaps the forecast period (never fabricated); the "
    "AI assistant answers household questions strictly from your data and the "
    "deterministic billing engine (household scope, INR/kWh)."
)

logging.basicConfig(
    level=getattr(logging, api_config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from .services import cache

    try:
        from .services import upload_service

        upload_service.clear_uploads()
        upload_service.cleanup_stale()
    except Exception as exc:  # noqa: BLE001 - never block startup on cleanup issues
        log.warning("startup upload cleanup skipped: %s", exc)

    try:
        cache.get_series()
        cache.get_model()
        log.info("startup: consumption series + forecast model cached")
    except Exception as exc:  # noqa: BLE001 - never block startup on missing artifacts
        log.warning("startup cache warm-up skipped: %s", exc)
    yield


app = FastAPI(
    title=APP_NAME,
    description=APP_DESCRIPTION,
    version=APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=f"{api_config.API_PREFIX}/openapi.json",
    lifespan=lifespan,
)

# --- CORS --------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=api_config.CORS_ORIGINS,
    allow_credentials=api_config.CORS_ORIGINS != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Structured errors ---------------------------------------------------------
def _json_error(status: int, code: str, message: str, details=None) -> JSONResponse:
    error: dict = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(status_code=status, content={"error": error})


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {
            "loc": list(e.get("loc", [])),
            "msg": e.get("msg", ""),
            "type": e.get("type", ""),
        }
        for e in exc.errors()
    ]
    return _json_error(422, "VALIDATION_ERROR", "Invalid request parameters or body", details)


@app.exception_handler(APIError)
async def api_error_handler(_request: Request, exc: APIError) -> JSONResponse:
    return _json_error(exc.status_code, exc.code, exc.message)


@app.exception_handler(ValueError)
async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
    return _json_error(400, "BAD_REQUEST", str(exc))


@app.exception_handler(FileNotFoundError)
async def file_not_found_handler(_request: Request, exc: FileNotFoundError) -> JSONResponse:
    return _json_error(404, "ARTIFACT_NOT_FOUND", str(exc))


@app.exception_handler(Exception)
async def unhandled_handler(_request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return _json_error(500, "INTERNAL_ERROR", "Internal server error")


# --- Register routers ----------------------------------------------------------
for module, prefix, tags in (
    (health, "", ["health"]),
    (consumption, api_config.API_PREFIX, ["consumption"]),
    (forecast, api_config.API_PREFIX, ["forecast"]),
    (weather, api_config.API_PREFIX, ["weather"]),
    (analytics, api_config.API_PREFIX, ["analytics"]),
    (anomalies, api_config.API_PREFIX, ["anomalies"]),
    (bills, api_config.API_PREFIX, ["bills"]),
    (agent, api_config.API_PREFIX, ["agent"]),
    (forecast_user, api_config.API_PREFIX, ["forecast"]),
):
    app.include_router(module.router, prefix=prefix)
