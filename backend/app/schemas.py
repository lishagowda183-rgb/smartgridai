"""Pydantic request/response schemas for the Phase 7 API.

Requests are strictly validated. Responses are validated through typed
``response_model`` envelopes: known fields are type-checked, and rich nested
payloads produced by the Phase 1-6 modules are passed through via
``extra="allow"`` so nothing is silently dropped.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Health / errors
# ---------------------------------------------------------------------------
class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    prefix: str
    docs: str
    redoc: str
    timestamp: str


class ErrorResponse(BaseModel):
    error: dict[str, Any]


# ---------------------------------------------------------------------------
# Consumption
# ---------------------------------------------------------------------------
class ConsumptionCurrentResponse(_Base):
    generated_at: str
    unit: str
    column: str
    scope: str
    series_start: str
    series_end: str
    count: int
    mean_mw: float
    min_mw: float
    max_mw: float
    latest: dict[str, Any]
    trailing_24h: list[dict[str, Any]]


class ConsumptionHistoryResponse(_Base):
    generated_at: str
    unit: str
    scope: str
    start: str | None
    end: str | None
    limit: int
    offset: int
    returned: int
    total_matching: int
    points: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------
class ForecastHourlyResponse(_Base):
    generated_at: str
    horizon: str
    horizon_hours: int
    unit: str
    model: str
    start: str
    end: str
    count: int
    points: list[dict[str, Any]]


class ForecastDailyResponse(_Base):
    generated_at: str
    horizon: str
    unit: str
    energy_unit: str
    model: str
    start: str
    end: str
    count: int
    days: list[dict[str, Any]]


class ForecastMonthlyResponse(_Base):
    generated_at: str
    horizon: str
    unit: str
    energy_unit: str
    model: str
    start: str
    end: str
    count: int
    months: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------
class WeatherCurrentResponse(_Base):
    generated_at: str
    source: str
    location: dict[str, Any]
    current: dict[str, Any]


class WeatherForecastResponse(_Base):
    generated_at: str
    source: str
    location: dict[str, Any]
    requested_days: int
    returned_hours: int
    start: str | None
    end: str | None
    points: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
class AnalyticsHourlyResponse(_Base):
    generated_at: str
    unit: str
    type: str
    points: list[dict[str, Any]]


class AnalyticsWeeklyResponse(_Base):
    generated_at: str
    unit: str
    type: str
    points: list[dict[str, Any]]


class AnalyticsMonthlyResponse(_Base):
    generated_at: str
    unit: str
    type: str
    points: list[dict[str, Any]]


class PeakHoursResponse(_Base):
    generated_at: str
    source: str
    artifact_generated_at: str | None
    series: dict[str, Any] | None
    peak_definition: dict[str, Any] | None
    summary: dict[str, Any] | None
    average_by_hour: list[dict[str, Any]] | None
    morning_peak_days: int | None
    evening_peak_days: int | None
    top_historical_peak_periods: list[dict[str, Any]] | None
    forecast: dict[str, Any] | None


class WeatherRelationshipResponse(_Base):
    generated_at: str
    source: str
    series: str
    unit: str
    n_rows: int
    range: dict[str, Any]
    correlations: list[dict[str, Any]]
    temperature_buckets: list[dict[str, Any]]


class HouseholdAnalyticsResponse(_Base):
    dataset_id: str
    filename: str
    unit: str | None = None
    frequency: str
    rows: int
    start_date: str
    end_date: str
    by_hour: list[dict[str, Any]] | None = None
    by_day_of_week: list[dict[str, Any]] = []
    by_month: list[dict[str, Any]] = []
    monthly_trend: list[dict[str, Any]] = []
    peak_hours: dict[str, Any] | None = None
    distribution: list[dict[str, Any]] = []
    weather_correlations: dict[str, Any] | None = None
    anomalies: dict[str, Any] | None = None
    generated_at: str


# ---------------------------------------------------------------------------
# Anomalies
# ---------------------------------------------------------------------------
class AnomalyResponse(_Base):
    generated_at: str
    source: str
    artifact_generated_at: str | None
    configuration: dict[str, Any] | None
    counts_by_method: dict[str, Any] | None
    counts_by_type: dict[str, Any] | None
    counts_by_severity: dict[str, Any] | None
    filters: dict[str, Any]
    returned: int
    total_matching: int
    anomalies: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Bills — Regional Grid Energy Cost
# ---------------------------------------------------------------------------
class RegionalBillResponse(_Base):
    generated_at: str
    currency: str
    mode: str
    units: dict[str, Any]
    horizon: str
    current_bill: dict[str, Any]
    _served_from: str | None = None
    _generated_at_api: str | None = None


class TariffListResponse(BaseModel):
    tariffs: list[str]


# ---------------------------------------------------------------------------
# Bills — Household Bill Simulator (per-kWh)
# ---------------------------------------------------------------------------
class HouseholdCalculateRequest(BaseModel):
    monthly_kwh: float = Field(..., ge=0, description="Monthly household consumption in kWh")
    tariff: str | None = Field(
        None, description="Household tariff name (default household_slabs)"
    )
    peak_share_pct: float = Field(
        40.0, ge=0, le=100, description="% of consumption billed at the peak rate (TOU only)"
    )


class HouseholdWhatIfRequest(BaseModel):
    monthly_kwh: float = Field(..., ge=0, description="Base monthly household consumption in kWh")
    tariff: str | None = Field(
        None, description="Household tariff name (default household_slabs)"
    )
    plus_pct: float = Field(10.0, ge=-100, le=1000, description="Consumption increase %")
    minus_pct: float = Field(10.0, ge=-100, le=1000, description="Consumption decrease %")
    custom_kwh: float | None = Field(None, ge=0, description="Custom scenario consumption (kWh)")
    peak_share_pct: float = Field(40.0, ge=0, le=100, description="% at peak rate (TOU only)")
    peak_shift_pct: float = Field(
        10.0, ge=0, le=100, description="% of peak kWh shifted off-peak (TOU only)"
    )


class HouseholdBillResponse(_Base):
    scope: str
    scope_label: str
    reporting_period: str
    consumption_unit: str
    energy_unit: str
    tariff_unit: str
    total: float
    monthly_consumption_kwh: float


class HouseholdWhatIfResponse(_Base):
    scope: str
    scope_label: str
    reporting_period: str
    consumption_unit: str
    energy_unit: str
    tariff_unit: str
    base: dict[str, Any]
    bill_difference: dict[str, Any]
    plus_10pct: dict[str, Any]
    minus_10pct: dict[str, Any]
    custom: dict[str, Any] | None
    estimated_savings: dict[str, Any] | None


# ---------------------------------------------------------------------------
# Agent — AI Energy Analyst (Phase 9)
# ---------------------------------------------------------------------------
class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="The user's energy question")
    conversation_id: str | None = Field(
        None, max_length=128, description="Optional conversation id (continued context)"
    )

    @field_validator("message")
    @classmethod
    def _message_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be empty")
        return value.strip()


class AgentDataPoint(BaseModel):
    label: str
    value: Any = None
    unit: str = ""


class AgentChatResponse(BaseModel):
    answer: str
    tools_used: list[str] = []
    data_points: list[AgentDataPoint] = []
    scope: str
    timestamp: str
    conversation_id: str
    model: str | None = None
    mode: str = "unknown"


# ---------------------------------------------------------------------------
# User upload + flexible forecasting (Phase 11)
# ---------------------------------------------------------------------------
class ForecastUploadResponse(_Base):
    dataset_id: str
    filename: str
    rows: int
    start_date: str
    end_date: str
    frequency: str
    timestamp_column: str
    consumption_column: str
    unit: str | None = None
    energy_unit: str | None = None
    scope: dict[str, Any] | None = None
    validation_status: str
    warnings: list[dict[str, Any]] = []


class ForecastDatasetResponse(_Base):
    dataset_id: str
    filename: str
    rows: int
    start_date: str
    end_date: str
    frequency: dict[str, Any]
    timestamp_column: str
    consumption_column: str
    unit: str | None = None
    scope: dict[str, Any] | None = None
    preview: list[dict[str, Any]] = []
    statistics: dict[str, Any] | None = None


class ForecastGenerateRequest(BaseModel):
    dataset_id: str = Field(..., description="dataset_id from POST /forecast/upload")
    horizon_value: int = Field(..., ge=1, le=730, description="Horizon number of days/months/years")
    horizon_unit: str | None = Field(
        "days", description="Horizon unit: days | months | years (case-insensitive)"
    )
    scope: str | None = Field(
        None, description="Optional scope override: household | regional_grid"
    )

    @field_validator("dataset_id")
    @classmethod
    def _dataset_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("dataset_id must not be empty")
        return value.strip()

    @field_validator("horizon_unit")
    @classmethod
    def _horizon_unit_known(cls, value: str | None) -> str | None:
        if value is None:
            return None
        key = value.strip().lower()
        if key not in ("days", "day", "months", "month", "years", "year"):
            raise ValueError("horizon_unit must be days, months or years")
        return key


class ForecastGenerateResponse(_Base):
    dataset_id: str
    filename: str
    horizon: dict[str, Any]
    forecast_type: str
    unit: str
    energy_unit: str
    scope: str
    display_granularity: str
    summary: dict[str, Any]
    classification: dict[str, Any]
    peak: dict[str, Any]
    points: list[dict[str, Any]]
    historical: list[dict[str, Any]] = []
    intervals_available: bool = True
    weather: dict[str, Any] | None = None
    recommendations: list[dict[str, Any]] = []
    household_bill: dict[str, Any] | None = None
    warning: str | None = None
    # Phase 3: festival/calendar block (calendar facts + observed household
    # effects + weather availability). Additive — never alters existing keys.
    festivals: dict[str, Any] | None = None


class ForecastDatasetListResponse(_Base):
    datasets: list[dict[str, Any]]
    total: int
    active_dataset_id: str | None = None


class ForecastDashboardResponse(_Base):
    dataset_id: str
    filename: str
    scope: str | None = None
    unit: str | None = None
    energy_unit: str | None = None
    frequency: str
    rows: int
    start_date: str
    end_date: str
    current: dict[str, Any]
    today: dict[str, Any] | None = None
    tomorrow: dict[str, Any] | None = None
    week: dict[str, Any] | None = None
    month: dict[str, Any] | None = None
    peak: dict[str, Any] | None = None
    status: str = "MEDIUM"
    model: str | None = None
    model_features: list[str] = []
    trend: str | None = None
    display_label: str | None = None
    weather: dict[str, Any] | None = None
    recommendations: list[dict[str, Any]] = []
    household_bill: dict[str, Any] | None = None
    points: list[dict[str, Any]] = []
    historical_tail: list[dict[str, Any]] = []
    onboarding: bool = False
    generated_at: str | None = None
    # Explainable household-relative classification stats (also surfaced on the
    # forecast page; readable by the AI assistant later, never computed by it).
    classification: dict[str, Any] | None = None
    warning: str | None = None
    # Phase 3: compact festival/calendar + observed-effect summary.
    festivals: dict[str, Any] | None = None