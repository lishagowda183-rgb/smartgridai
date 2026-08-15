"""Registered agent tools (household-only).

Each tool is a thin, read-only adapter over the existing service layer
(``backend/app/services``). Tools never recompute ML/weather/analytics/billing
values: they call the same deterministic services the REST endpoints use and
return their full real payloads.

Scope: this agent answers household questions ONLY. Numerical claims always come
from the uploaded dataset / deterministic engines; when no household dataset is
available the tools report an onboarding state instead of fabricating numbers.
Regional-grid tools (ENTSO-E/Madrid) are intentionally NOT in the allowlist.

Security: the LLM can ONLY call the tools registered here (the allowlist).
There are no tools that execute arbitrary code, shell commands, SQL, filesystem
access or arbitrary URLs.
"""

from __future__ import annotations

import logging
import time

from ..errors import AgentToolValidationError
from ..services import household_analytics, household_dashboard, upload_service, weather

log = logging.getLogger("api.agent.tools")

ONBOARDING_MESSAGE = (
    "No household consumption data uploaded yet. Upload a CSV/XLSX file first; "
    "the AI assistant then works only with your own data."
)

# --- argument validation helpers (hand-rolled, no extra dependency) -----------


def _str(arg, name, allowed: set[str] | None = None, default=None) -> str | None:
    if arg is None:
        return default
    if not isinstance(arg, str) or not arg.strip():
        raise AgentToolValidationError(f"'{name}' must be a non-empty string")
    value = arg.strip()
    if allowed is not None and value not in allowed:
        raise AgentToolValidationError(
            f"'{name}' must be one of {sorted(allowed)}, got '{value}'"
        )
    return value


def _num(arg, name, minimum=None, maximum=None, default=None, integer: bool = False) -> float | int | None:
    if arg is None:
        return default
    try:
        value = float(arg)
    except (TypeError, ValueError):
        raise AgentToolValidationError(f"'{name}' must be a number, got {arg!r}")
    if integer and value != int(value):
        raise AgentToolValidationError(f"'{name}' must be an integer, got {value!r}")
    if minimum is not None and value < minimum:
        raise AgentToolValidationError(f"'{name}' must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise AgentToolValidationError(f"'{name}' must be <= {maximum}")
    return int(value) if integer else value


def _resolve_dataset(dataset_id: str | None) -> str | None:
    """Explicit dataset_id (validated) or the active household dataset."""
    if dataset_id:
        upload_service.get_metadata(dataset_id)  # raises NotFound for unknown ids
        return dataset_id
    active = household_dashboard._active_household_dataset()
    return active["dataset_id"] if active else None


# ---------------------------------------------------------------------------
# Tools (household only; each returns real service payloads)
# ---------------------------------------------------------------------------
def get_active_dataset(__args__: dict) -> dict:
    """Tool: the active household dataset (or an onboarding state if none)."""
    data = household_dashboard.datasets()
    active = data.get("active_dataset_id")
    if active is None:
        return {"available": False, "message": ONBOARDING_MESSAGE, "active_dataset_id": None}
    item = next((d for d in data["datasets"] if d["dataset_id"] == active), None)
    return {"available": True, "active_dataset_id": active, "dataset": item}


def get_household_overview(__args__: dict) -> dict:
    """Tool: weather-aware household dashboard (current / today / tomorrow /
    week / month / peak / status / model / weather / bill)."""
    dataset_id = _str(__args__.get("dataset_id"), "dataset_id")
    try:
        payload = household_dashboard.dashboard(dataset_id)
    except Exception as exc:  # noqa: BLE001 - onboarding/unknown handled honestly
        return {"available": False, "message": str(exc) or ONBOARDING_MESSAGE}
    payload["available"] = True
    return payload


def get_current_consumption(__args__: dict) -> dict:
    """Tool: the household's latest reading + today's total (read straight from
    the uploaded series — no forecast recomputed)."""
    dataset_id = _str(__args__.get("dataset_id"), "dataset_id")
    try:
        resolved = _resolve_dataset(dataset_id)
        if resolved is None:
            return {"available": False, "message": ONBOARDING_MESSAGE}
        series = upload_service.get_series(resolved)
        meta = upload_service.get_metadata(resolved)
        freq = meta["frequency"]["label"]
        unit = (meta["scope"] or {}).get("unit") or "kWh"
        latest_ts = series.index.max()
        latest_value = float(series.iloc[-1])
        subdaily = freq in ("hourly", "30min", "15min", "minutely")
        tail = series.tail(24) if subdaily else series.tail(1)
        today_idx = series[series.index.normalize() == latest_ts.normalize()]
        return {
            "available": True,
            "dataset_id": resolved,
            "scope": (meta["scope"] or {}).get("scope"),
            "unit": unit,
            "frequency": freq,
            "latest_timestamp": str(latest_ts),
            "latest_reading": round(latest_value, 3),
            "today_total": round(float(today_idx.sum()), 3),
            "trailing_total": round(float(tail.sum()), 3),
            "note": "Read from the latest values of the uploaded household dataset.",
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "message": str(exc) or ONBOARDING_MESSAGE}


def get_household_classification(__args__: dict) -> dict:
    """Tool: household-relative LOW/MEDIUM/HIGH classification and WHY (from the
    deterministic forecast engine, never recomputed by the agent)."""
    dataset_id = _str(__args__.get("dataset_id"), "dataset_id")
    try:
        payload = household_dashboard.dashboard(dataset_id)
    except Exception as exc:  # noqa: BLE001 - onboarding/unknown handled honestly
        return {"available": False, "message": str(exc) or ONBOARDING_MESSAGE}
    cls = payload.get("classification") or {}
    return {
        "available": True,
        "status": payload.get("status"),
        "classification": cls,
        "reason": cls.get("reason"),
        "historical_mean": cls.get("historical_mean"),
        "forecast_mean": cls.get("forecast_mean"),
        "forecast_change_percent": cls.get("forecast_change_percent"),
        "historical_90th_percentile": cls.get("historical_90th_percentile"),
        "high_period_count": cls.get("high_period_count"),
        "high_period_percentage": cls.get("high_period_percentage"),
        "forecast_peak": cls.get("forecast_peak"),
        "warning": cls.get("warning") or payload.get("warning"),
        "trend": payload.get("trend"),
        "unit": payload.get("unit"),
        "scope": "household",
        "weather": payload.get("weather"),
    }


def get_user_forecast(__args__: dict) -> dict:
    """Tool: flexible forecast on the uploaded data (1d..2y horizons)."""
    from ..services import user_forecast

    dataset_id = _str(__args__.get("dataset_id"), "dataset_id")
    resolved = _resolve_dataset(dataset_id)
    if resolved is None:
        return {"available": False, "message": ONBOARDING_MESSAGE}
    horizon_value = _num(__args__.get("horizon_value"), "horizon_value",
                         minimum=1, maximum=730, integer=True, default=7)
    horizon_unit = _str(__args__.get("horizon_unit"), "horizon_unit",
                        allowed={"days", "day", "months", "month", "years", "year"},
                        default="days")
    scope = _str(__args__.get("scope"), "scope",
                 allowed={"household", "regional_grid"}, default=None)
    payload = user_forecast.generate(resolved, horizon_value, horizon_unit, scope)
    payload["available"] = True
    payload["dataset_id"] = resolved
    return payload


def get_user_analytics(__args__: dict) -> dict:
    """Tool: household usage patterns + weather correlations + anomalies."""
    dataset_id = _str(__args__.get("dataset_id"), "dataset_id")
    try:
        payload = household_analytics.analytics(dataset_id)
    except Exception as exc:  # noqa: BLE001 - onboarding/unknown handled honestly
        return {"available": False, "message": str(exc) or ONBOARDING_MESSAGE}
    payload["available"] = True
    return payload


def get_user_anomalies(__args__: dict) -> dict:
    """Tool: rolling-z anomalies on the uploaded history (observed/expected/severity)."""
    dataset_id = _str(__args__.get("dataset_id"), "dataset_id")
    try:
        payload = household_analytics.analytics(dataset_id)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "message": str(exc) or ONBOARDING_MESSAGE}
    anomalies = payload.get("anomalies") or {}
    ans = {
        "available": bool(anomalies.get("available", False)),
        "note": None if anomalies.get("available") else anomalies.get("note"),
        "count": anomalies.get("count", 0),
        "window": anomalies.get("window"),
        "threshold": anomalies.get("threshold"),
        "anomalies": anomalies.get("anomalies", []),
        "unit": payload.get("unit"),
    }
    if not ans["available"]:
        ans["message"] = ans["note"] or ONBOARDING_MESSAGE
    return ans


def get_festival_outlook(__args__: dict) -> dict:
    """Tool: deterministic festival calendar + the household's OWN observed
    festival effect (Phase 13 engine). Never assumes festival == high usage."""
    from ..services import festival_calendar

    dataset_id = _str(__args__.get("dataset_id"), "dataset_id")
    horizon_days = _num(__args__.get("horizon_days"), "horizon_days",
                        minimum=1, maximum=730, integer=True, default=365)
    try:
        resolved = _resolve_dataset(dataset_id)
        if resolved is None:
            return {"available": False, "message": ONBOARDING_MESSAGE}
        series = upload_service.get_series(resolved)
        meta = upload_service.get_metadata(resolved)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "message": str(exc) or ONBOARDING_MESSAGE}

    analysis = festival_calendar.analyze_historical_festivals(series)
    upcoming = festival_calendar.upcoming_festivals(
        series.index.max(), int(horizon_days), analysis)
    up = upcoming or []
    next_f = up[0] if up else None
    return {
        "available": True,
        "dataset_id": resolved,
        "unit": (meta["scope"] or {}).get("unit") or "kWh",
        "scope": "household",
        "horizon_days": int(horizon_days),
        "analysis": analysis,
        "upcoming": upcoming,
        "summary": {
            "analyzed_festivals": len(analysis),
            "analyzed_with_effect": sum(1 for a in analysis if a.get("data_available")),
            "next_festival_name": next_f.get("festival_name") if next_f else None,
            "next_festival_date": next_f.get("date") if next_f else None,
            "next_festival_class": (next_f.get("historical_classification")
                                    if next_f and next_f.get("festival_data_available") else None),
            "insufficient_data": bool(next_f and not next_f.get("festival_data_available")),
        },
        "note": festival_calendar.CALENDAR_ATTR,
        "classification_labels": {
            "HIGHER_THAN_NORMAL": "consumed more than normal around this festival",
            "LOWER_THAN_NORMAL": "consumed less than normal around this festival",
            "SIMILAR_TO_NORMAL": "consumption was similar to normal",
        },
    }


def get_weather(__args__: dict) -> dict:
    """Tool: current observation or next-day hourly weather forecast."""
    mode = _str(__args__.get("mode"), "mode", allowed={"current", "forecast"}, default="current")
    if mode == "forecast":
        result = weather.forecast(days=1)
        result["notes"] = "Weather is served from the persisted Open-Meteo snapshot (read-only)."
        return result
    return weather.current()


def calculate_household_bill(__args__: dict) -> dict:
    """Tool: deterministic household bill for a monthly kWh figure."""
    kwh = _num(__args__.get("consumption_kwh"), "consumption_kwh", minimum=0, default=None)
    if kwh is None:
        raise AgentToolValidationError("consumption_kwh is required")
    tariff = _str(__args__.get("tariff"), "tariff", default=None)
    peak_share = _num(
        __args__.get("peak_share_pct"), "peak_share_pct",
        minimum=0, maximum=100, default=40,
    )
    from ..services import bills
    return bills.household_calculate(monthly_kwh=kwh, tariff=tariff, peak_share_pct=peak_share)


def calculate_household_what_if(__args__: dict) -> dict:
    """Tool: deterministic household what-if (+/-% OR a custom target kWh)."""
    kwh = _num(__args__.get("consumption_kwh"), "consumption_kwh", minimum=0, default=None)
    if kwh is None:
        raise AgentToolValidationError("consumption_kwh is required")
    change = _num(__args__.get("change_percent"), "change_percent",
                  minimum=-100, maximum=100, default=None)
    target_kwh = _num(__args__.get("target_consumption_kwh"), "target_consumption_kwh",
                      minimum=0, default=None)
    if change is None and target_kwh is None:
        raise AgentToolValidationError(
            "change_percent or target_consumption_kwh is required"
        )
    from ..services import bills
    if target_kwh is not None:
        raw = bills.household_what_if(
            monthly_kwh=kwh,
            tariff=None,
            plus_pct=10.0,
            minus_pct=10.0,
            custom_kwh=target_kwh,
            peak_share_pct=40,
            peak_shift_pct=10,
        )
        scenario = raw.get("custom") or {}
        base = raw["base"]
        change = scenario.get("change_pct")
        return {
            "scope": raw.get("scope"),
            "scope_label": raw.get("scope_label"),
            "reporting_period": raw.get("reporting_period"),
            "consumption_unit": raw.get("consumption_unit"),
            "tariff_unit": raw.get("tariff_unit"),
            "original_consumption_kwh": kwh,
            "target_consumption_kwh": target_kwh,
            "scenario": "custom",
            "changed_consumption_kwh": scenario.get("monthly_consumption_kwh"),
            "change_percent": change,
            "original_bill_total": base.get("total"),
            "new_bill_total": scenario.get("total"),
            "difference": (scenario.get("total") or 0) - (base.get("total") or 0),
            "difference_pct": scenario.get("change_pct"),
            "estimated_savings": raw.get("estimated_savings"),
            "currency": "INR",
        }
    pct = abs(float(change))
    raw = bills.household_what_if(
        monthly_kwh=kwh,
        tariff=None,
        plus_pct=pct,
        minus_pct=pct,
        custom_kwh=None,
        peak_share_pct=40,
        peak_shift_pct=10,
    )
    scenario = raw["minus_10pct"] if change < 0 else raw["plus_10pct"]
    base = raw["base"]
    return {
        "scope": raw.get("scope"),
        "scope_label": raw.get("scope_label"),
        "reporting_period": raw.get("reporting_period"),
        "consumption_unit": raw.get("consumption_unit"),
        "tariff_unit": raw.get("tariff_unit"),
        "original_consumption_kwh": kwh,
        "changed_consumption_kwh": scenario.get("consumption_kwh"),
        "change_percent": float(change),
        "original_bill_total": base.get("total"),
        "new_bill_total": scenario.get("total"),
        "difference": (scenario.get("total") or 0) - (base.get("total") or 0),
        "difference_pct": scenario.get("change_pct"),
        "estimated_savings": raw.get("estimated_savings"),
        "currency": "INR",
    }


# ---------------------------------------------------------------------------
# Registry + allowlist
# ---------------------------------------------------------------------------
TOOL_PARAMETERS: dict[str, dict] = {
    "get_active_dataset": {"type": "object", "properties": {}, "required": []},
    "get_household_overview": {
        "type": "object",
        "properties": {
            "dataset_id": {"type": "string", "description": "Optional dataset_id (defaults to the active household dataset)."},
        },
        "required": [],
    },
    "get_user_forecast": {
        "type": "object",
        "properties": {
            "dataset_id": {"type": "string", "description": "Optional dataset_id (defaults to the active household dataset)."},
            "horizon_value": {"type": "integer", "minimum": 1, "maximum": 730, "description": "Forecast horizon value, e.g. 7, 30, 2"},
            "horizon_unit": {"type": "string", "enum": ["days", "day", "months", "month", "years", "year"], "description": "Forecast horizon unit"},
            "scope": {"type": "string", "enum": ["household", "regional_grid"], "description": "Optional scope override"},
        },
        "required": [],
    },
    "get_user_analytics": {
        "type": "object",
        "properties": {
            "dataset_id": {"type": "string", "description": "Optional dataset_id (defaults to the active household dataset)."},
        },
        "required": [],
    },
    "get_user_anomalies": {
        "type": "object",
        "properties": {
            "dataset_id": {"type": "string", "description": "Optional dataset_id (defaults to the active household dataset)."},
        },
        "required": [],
    },
    "get_festival_outlook": {
        "type": "object",
        "properties": {
            "dataset_id": {"type": "string", "description": "Optional dataset_id (defaults to the active household dataset)."},
            "horizon_days": {"type": "integer", "minimum": 1, "maximum": 730, "description": "How many days ahead to look for upcoming festivals (default 365)."},
        },
        "required": [],
    },
    "get_current_consumption": {
        "type": "object",
        "properties": {
            "dataset_id": {"type": "string", "description": "Optional dataset_id (defaults to the active household dataset)."},
        },
        "required": [],
    },
    "get_household_classification": {
        "type": "object",
        "properties": {
            "dataset_id": {"type": "string", "description": "Optional dataset_id (defaults to the active household dataset)."},
        },
        "required": [],
    },
    "get_weather": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["current", "forecast"], "description": "current observation or next-day hourly forecast"},
        },
        "required": ["mode"],
    },
    "calculate_household_bill": {
        "type": "object",
        "properties": {
            "consumption_kwh": {"type": "number", "minimum": 0, "description": "Monthly household consumption in kWh"},
            "tariff": {"type": "string", "description": "Household tariff name (default household_slabs)"},
            "peak_share_pct": {"type": "number", "minimum": 0, "maximum": 100, "description": "(TOU only)"},
        },
        "required": ["consumption_kwh"],
    },
    "calculate_household_what_if": {
        "type": "object",
        "properties": {
            "consumption_kwh": {"type": "number", "minimum": 0, "description": "Base monthly household consumption in kWh"},
            "change_percent": {"type": "number", "minimum": -100, "maximum": 100, "description": "Planned consumption % change (negative = reduction)"},
            "target_consumption_kwh": {"type": "number", "minimum": 0, "description": "Alternative: a custom monthly kWh target ('what if I use 300 kWh?')"},
        },
        "required": ["consumption_kwh"],
    },
}

REGISTRY: dict[str, dict] = {
    "get_active_dataset": {
        "description": "The active uploaded household dataset (or an onboarding note when none exists).",
        "fn": get_active_dataset,
    },
    "get_household_overview": {
        "description": "Your household dashboard: current/today/tomorrow/week/month totals, peak, status, model, weather availability, estimated bill + recommendations.",
        "fn": get_household_overview,
    },
    "get_current_consumption": {
        "description": "Your latest household reading and today's total (straight from the uploaded data — no forecast).",
        "fn": get_current_consumption,
    },
    "get_household_classification": {
        "description": "Your LOW/MEDIUM/HIGH household classification and why (historical vs forecast mean, % change, high-period share, peak, reason) — always from the deterministic forecast engine.",
        "fn": get_household_classification,
    },
    "get_user_forecast": {
        "description": "A flexible forecast for your uploaded data (1..730 days/months/years; e.g. next week, next month, next 1-2 years). The forecast engine is the source of truth; never invent predictions. Also returns weather availability and festival/calendar info.",
        "fn": get_user_forecast,
    },
    "get_festival_outlook": {
        "description": "Deterministic Indian festival calendar + the household's own OBSERVED festival effect (higher/lower/similar, only when enough history exists). Never assume a festival means high usage.",
        "fn": get_festival_outlook,
    },
    "get_user_analytics": {
        "description": "Household usage patterns (hour/day/month), peak hours, distribution, weather-consumption correlations (only if real weather overlaps) + anomalies.",
        "fn": get_user_analytics,
    },
    "get_user_anomalies": {
        "description": "Rolling-z-score anomalies on your history (observed, historical average, deviation, severity).",
        "fn": get_user_anomalies,
    },
    "get_weather": {
        "description": "Current weather observation or next-day hourly forecast (from the persisted Open-Meteo snapshot).",
        "fn": get_weather,
    },
    "calculate_household_bill": {
        "description": "Deterministic household bill (INR/kWh) for a monthly kWh figure. The billing engine is the source of truth.",
        "fn": calculate_household_bill,
    },
    "calculate_household_what_if": {
        "description": "Deterministic household what-if: how the bill changes for a +/-% consumption change OR a custom monthly kWh target (INR).",
        "fn": calculate_household_what_if,
    },
}


def tool_specs() -> list[dict]:
    """OpenAI-style function specs for the LLM (name/description/parameters)."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": TOOL_PARAMETERS[name],
            },
        }
        for name, spec in REGISTRY.items()
    ]


def allowed_tool_names() -> list[str]:
    return sorted(REGISTRY.keys())


def execute(name: str, arguments: dict, start: float | None = None) -> dict:
    """Run a registered tool. Raises AgentToolValidationError for bad args/tool."""
    if name not in REGISTRY:
        raise AgentToolValidationError(f"unknown tool '{name}'. Allowed: {allowed_tool_names()}")
    if not isinstance(arguments, dict):
        raise AgentToolValidationError("tool arguments must be a JSON object")
    schema = TOOL_PARAMETERS[name]
    _validate_schema(name, schema, arguments)
    t0 = time.perf_counter()
    try:
        payload = REGISTRY[name]["fn"](arguments)
    except AgentToolValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface as tool error, never crash the agent
        log.warning("tool %s failed: %s", name, exc)
        raise AgentToolValidationError(f"tool '{name}' failed: {exc}") from exc
    finally:
        if start is not None:
            log.info("tool=%s duration_ms=%.1f", name, (time.perf_counter() - start) * 1000)
    return payload


# --- lightweight JSON-schema validation ---------------------------------------


def _validate_schema(name: str, schema: dict, args: dict) -> None:
    props = schema.get("properties", {})
    for required in schema.get("required", []):
        if required not in args or args[required] is None:
            raise AgentToolValidationError(f"tool '{name}' requires argument '{required}'")
    for key, value in args.items():
        spec = props.get(key)
        if spec is None:
            raise AgentToolValidationError(f"tool '{name}' received unknown argument '{key}'")
        if value is None:
            continue
        _validate_value(name, key, value, spec)


def _validate_value(name: str, key: str, value, spec: dict) -> None:
    if spec.get("type") == "integer":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != int(value):
            raise AgentToolValidationError(f"tool '{name}' argument '{key}' must be an integer")
        value = int(value)
    elif spec.get("type") == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AgentToolValidationError(f"tool '{name}' argument '{key}' must be a number")
    elif spec.get("type") == "string":
        if not isinstance(value, str):
            raise AgentToolValidationError(f"tool '{name}' argument '{key}' must be a string")
    if "enum" in spec and value not in spec["enum"]:
        raise AgentToolValidationError(
            f"tool '{name}' argument '{key}' must be one of {spec['enum']}, got {value!r}"
        )
    if spec.get("minimum") is not None and value < spec["minimum"]:
        raise AgentToolValidationError(f"tool '{name}' argument '{key}' must be >= {spec['minimum']}")
    if spec.get("maximum") is not None and value > spec["maximum"]:
        raise AgentToolValidationError(f"tool '{name}' argument '{key}' must be <= {spec['maximum']}")


# --- deterministic data-point extraction (for the response, never invented) ----


def extract_points(name: str, result: dict) -> list[dict]:
    try:
        return _extract(name, result)
    except Exception:  # noqa: BLE001 - extraction is best-effort
        return []


def _extract(name: str, result: dict) -> list[dict]:
    if result.get("available") is False:
        return []
    if name == "get_active_dataset":
        return [
            {"label": "Dataset", "value": result.get("active_dataset_id") or "none",
             "unit": ""},
        ]
    if name == "get_household_overview":
        current = result.get("current") or {}
        week = result.get("week") or {}
        month = result.get("month") or {}
        peak = result.get("peak") or {}
        return [
            {"label": "Latest value", "value": current.get("value"), "unit": result.get("unit", "kWh")},
            {"label": "This week total", "value": week.get("total"), "unit": "kWh"},
            {"label": "Month total", "value": month.get("total"), "unit": "kWh"},
            {"label": "Peak value", "value": peak.get("value"), "unit": result.get("unit", "kWh")},
            {"label": "Status", "value": result.get("status"), "unit": ""},
        ]
    if name == "get_user_forecast":
        summary = result.get("summary") or {}
        peak = result.get("peak") or {}
        return [
            {"label": "Forecast average", "value": summary.get("average"),
             "unit": result.get("unit", "kWh")},
            {"label": "Forecast total", "value": summary.get("total"),
             "unit": result.get("unit", "kWh")},
            {"label": "Peak", "value": peak.get("value"), "unit": result.get("unit", "kWh")},
            {"label": "Model", "value": result.get("model"), "unit": ""},
        ]
    if name == "get_user_analytics":
        ph = result.get("peak_hours") or {}
        peak = (ph.get("peak_hours") or [{}])[0].get("hour")
        return [
            {"label": "Peak hour", "value": peak, "unit": "hour of day"},
            {"label": "Peak-to-average ratio", "value": (ph.get("peak_to_average_ratio")),
             "unit": ""},
            {"label": "Anomalies", "value": (result.get("anomalies") or {}).get("count", 0),
             "unit": ""},
        ]
    if name == "get_user_anomalies":
        return [
            {"label": "Anomalies returned", "value": result.get("count"), "unit": ""},
            {"label": "Threshold (z)", "value": result.get("threshold"), "unit": ""},
        ]
    if name == "get_weather":
        if "current" in result:
            c = result.get("current") or {}
            return [
                {"label": "Temperature", "value": c.get("temperature_c"), "unit": "°C"},
                {"label": "Humidity", "value": c.get("humidity_pct"), "unit": "%"},
                {"label": "Condition", "value": c.get("condition"), "unit": ""},
            ]
        pts = result.get("points") or []
        return [{"label": "Forecast hours", "value": len(pts), "unit": "h"}]
    if name == "calculate_household_bill":
        return [
            {"label": "Household bill total", "value": result.get("total"), "unit": "INR"},
            {"label": "Consumption", "value": result.get("monthly_consumption_kwh"), "unit": "kWh"},
            {"label": "Reporting period", "value": result.get("reporting_period"), "unit": ""},
        ]
    if name == "calculate_household_what_if":
        return [
            {"label": "Original bill", "value": result.get("original_bill_total"), "unit": "INR"},
            {"label": "New bill", "value": result.get("new_bill_total"), "unit": "INR"},
            {"label": "Difference", "value": result.get("difference"), "unit": "INR"},
            {"label": "Change", "value": result.get("difference_pct"), "unit": "%"},
        ]
    if name == "get_current_consumption":
        return [
            {"label": "Latest reading", "value": result.get("latest_reading"),
             "unit": result.get("unit", "kWh")},
            {"label": "Today total", "value": result.get("today_total"),
             "unit": result.get("unit", "kWh")},
        ]
    if name == "get_household_classification":
        cls = result.get("classification") or {}
        return [
            {"label": "Status", "value": result.get("status"), "unit": ""},
            {"label": "Historical mean", "value": cls.get("historical_mean"),
             "unit": result.get("unit", "kWh")},
            {"label": "Forecast mean", "value": cls.get("forecast_mean"),
             "unit": result.get("unit", "kWh")},
            {"label": "Forecast change", "value": cls.get("forecast_change_percent"), "unit": "%"},
            {"label": "High-period share", "value": cls.get("high_period_percentage"), "unit": "%"},
        ]
    if name == "get_festival_outlook":
        up = result.get("upcoming") or []
        summary = result.get("summary") or {}
        return [
            {"label": "Next festival", "value": summary.get("next_festival_name"),
             "unit": ""},
            {"label": "Festival effect",
             "value": summary.get("next_festival_class") or "insufficient_data",
             "unit": ""},
            {"label": "Festivals analyzed", "value": summary.get("analyzed_festivals"), "unit": ""},
        ]
    return []