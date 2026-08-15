"""Consumption routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ... import config as api_config
from ...schemas import ConsumptionCurrentResponse, ConsumptionHistoryResponse
from ...services import consumption

router = APIRouter(prefix="/consumption", tags=["consumption"])


@router.get("/current", response_model=ConsumptionCurrentResponse, summary="Latest reading + series summary")
def current() -> dict:
    return consumption.current()


@router.get("/history", response_model=ConsumptionHistoryResponse, summary="Sliced history of the series")
def history(
    start: str | None = Query(None, description="Inclusive start date (YYYY-MM-DD or ISO)"),
    end: str | None = Query(None, description="Inclusive end date (YYYY-MM-DD or ISO)"),
    limit: int = Query(api_config.DEFAULT_HISTORY_LIMIT, ge=1, le=api_config.MAX_HISTORY_LIMIT),
    offset: int = Query(0, ge=0),
) -> dict:
    return consumption.history(start=start, end=end, limit=limit, offset=offset)