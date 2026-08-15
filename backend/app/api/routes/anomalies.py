"""Anomaly routes (persisted anomaly_report.json)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ... import config as api_config
from ...schemas import AnomalyResponse
from ...services import anomalies as svc

router = APIRouter(prefix="/anomalies", tags=["anomalies"])

VALID_METHODS = {"rolling_zscore", "hourly_profile", "nighttime", "isolation_forest"}
VALID_SEVERITIES = {"moderate", "high", "critical"}


@router.get("", response_model=AnomalyResponse, summary="Detected anomalies (filtered)")
def list_anomalies(
    severity: str | None = Query(None, description="Filter by severity: moderate/high/critical"),
    method: str | None = Query(None, description="Filter by detection method"),
    limit: int = Query(500, ge=1, le=api_config.MAX_ANOMALY_LIMIT),
) -> dict:
    if severity and severity not in VALID_SEVERITIES:
        raise ValueError(f"severity must be one of {sorted(VALID_SEVERITIES)}")
    if method and method not in VALID_METHODS:
        raise ValueError(f"method must be one of {sorted(VALID_METHODS)}")
    return svc.anomalies(severity=severity, method=method, limit=limit)