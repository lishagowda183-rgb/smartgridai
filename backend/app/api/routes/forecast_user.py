"""User upload + flexible forecasting routes (Phase 11).

Multipart upload is handled with FastAPI's ``UploadFile`` (streamed, size
limited); datasets live behind generated dataset_ids in the (gitignored)
uploads dir and are never mixed with the original project series.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import Response

from ... import config as api_config
from ...errors import BadRequestError
from ...schemas import (
    ForecastDashboardResponse,
    ForecastDatasetListResponse,
    ForecastDatasetResponse,
    ForecastGenerateRequest,
    ForecastGenerateResponse,
    ForecastUploadResponse,
)
from ...services import household_dashboard
from ...services import upload_service as uploads
from ...services import user_forecast

router = APIRouter(prefix="/forecast", tags=["forecast-upload"])


@router.post(
    "/upload",
    response_model=ForecastUploadResponse,
    summary="Upload + validate a consumption file (CSV/XLSX)",
)
async def upload(file: UploadFile = File(..., description="CSV or XLSX consumption file")) -> dict:
    content = await file.read()
    if len(content) > api_config.MAX_UPLOAD_SIZE:
        raise BadRequestError(
            f"upload too large ({len(content) / 1e6:.1f} MB). "
            f"Max: {api_config.MAX_UPLOAD_SIZE_MB} MB"
        )
    return uploads.process_upload(file.filename or "upload", content)


@router.get(
    "/datasets/{dataset_id}",
    response_model=ForecastDatasetResponse,
    summary="Dataset metadata + preview (confirmation screen)",
)
def dataset(dataset_id: str) -> dict:
    return uploads.dataset_report(dataset_id)


@router.post(
    "/generate",
    response_model=ForecastGenerateResponse,
    summary="Generate a flexible forecast for an uploaded dataset",
)
def generate(req: ForecastGenerateRequest) -> dict:
    return user_forecast.generate(req.dataset_id, req.horizon_value, req.horizon_unit, req.scope)


@router.get(
    "/datasets",
    response_model=ForecastDatasetListResponse,
    summary="List uploaded datasets (newest first) + active dashboard dataset",
)
def list_datasets(limit: int = Query(5, ge=1, le=20)) -> dict:
    return household_dashboard.datasets(limit)


@router.get(
    "/dashboard",
    response_model=ForecastDashboardResponse,
    summary="Weather-aware household dashboard (uses the active uploaded dataset)",
    responses={404: {"description": "No dataset uploaded yet (onboarding state)"}},
)
def dashboard(
    dataset_id: str | None = Query(None, description="dataset_id; defaults to the newest household dataset"),
) -> dict:
    """Household dashboard: today/tomorrow/week/month totals, peak, weather
    status, model, trend, bill + recommendations — all from the uploaded data
    (404 with an onboarding message when there is no dataset)."""
    return household_dashboard.dashboard(dataset_id)


@router.get(
    "/export",
    summary="Export forecast results as CSV",
    responses={200: {"content": {"text/csv": {}}, "description": "Forecast CSV"}},
)
def export(
    dataset_id: str = Query(..., description="dataset_id from POST /forecast/upload"),
    horizon_value: int = Query(..., ge=1, le=730),
    horizon_unit: str = Query("days"),
    scope: str | None = Query(None),
) -> Response:
    """CSV export of the forecast points (timestamp, predicted, bounds, class)."""
    payload = user_forecast.generate(dataset_id, horizon_value, horizon_unit, scope)
    filename = f"forecast_{dataset_id}_{horizon_value}{horizon_unit}.csv"
    csv_bytes: bytes = user_forecast.export_csv(payload).encode("utf-8-sig")
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/export/summary",
    summary="Export a compact forecast summary as CSV",
    responses={200: {"content": {"text/csv": {}}, "description": "Summary CSV"}},
)
def export_summary(
    dataset_id: str = Query(...),
    horizon_value: int = Query(..., ge=1, le=730),
    horizon_unit: str = Query("days"),
    scope: str | None = Query(None),
) -> Response:
    payload = user_forecast.generate(dataset_id, horizon_value, horizon_unit, scope)
    filename = f"forecast_summary_{dataset_id}.csv"
    csv_bytes: bytes = user_forecast.export_summary(payload).encode("utf-8-sig")
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Exposed here so the router module remains discoverable/importable standalone.
ALLOWED_EXTENSIONS: list[str] = api_config.ALLOWED_UPLOAD_EXTENSIONS