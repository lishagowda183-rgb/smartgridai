"""User-uploaded forecast pipeline (Phase 11).

Runs a forecast on an uploaded dataset (never the original project series):

  * horizon validation + strategy selection (short / medium / long term)
  * short-term: an ML model retrained on the uploaded history (existing
    feature_engineering + forecasting.build_xgboost recipe + the existing
    iterated_forecast), so it is always scale-correct for that dataset.
  * medium/long-term: a deterministic seasonal-trend model (linear trend x
    month/day-of-week/hour factors) computed from the uploaded history.
  * classification (LOW/MEDIUM/HIGH from uploaded percentiles), peak analysis,
    deterministic recommendations, optional household bill (household-only),
    and CSV export.

Weather: only ever reported as *available* when the persisted weather
forecast actually covers the forecast period. Future weather is never
fabricated — long-term forecasts are explicitly labelled as using historical
weather relationships and seasonality.
"""

from __future__ import annotations

import io
import logging
from functools import lru_cache

import numpy as np
import pandas as pd

from .. import config as api_config  # noqa: E402 (bootstraps ml/scripts sys.path)

import config as ml_config  # noqa: E402

from ..errors import BadRequestError, NotFoundError  # noqa: E402
from . import cache as api_cache  # noqa: E402
from . import festival_calendar  # noqa: E402
from . import upload_service  # noqa: E402
from . import weather  # noqa: E402
from .forecast_classification import (  # noqa: E402
    classification_summary,
    classify_value,
    classify_values,
    thresholds_from_history,
)
from .recommendations import (  # noqa: E402
    evening_demand_share,
    generate_recommendations,
)

log = logging.getLogger("api.user_forecast")

HORIZON_UNITS = {"days": 0, "day": 0, "months": 1, "month": 1, "years": 2, "year": 2}
Z_MULT = 1.96  # ~95% prediction band
SUBDAILY = ("hourly", "30min", "15min", "minutely")

# Weather variables usable as extra predictive features. `condition` is the
# ordinal WMO category. These are NEVER fabricated: they are only joined when
# a real weather source overlaps the uploaded history / forecast period.
WEATHER_FEATURE_COLS = ["temperature", "humidity", "precipitation", "wind_speed", "condition"]

# Numeric festival/calendar features added to the short-term ML matrix. The
# model learns the household's own observed relationship (which may be above,
# below or level with normal) — never a forced positive effect.
FESTIVAL_FEATURE_COLS = [
    "is_festival",
    "is_holiday",
    "days_before_festival",
    "days_after_festival",
    "festival_day",
    "festival_window",
]


# ---------------------------------------------------------------------------
# Weather feature sources (real data only; monkeypatchable for tests)
# ---------------------------------------------------------------------------
def _historical_weather_frame():
    """Historical weather aligned exactly to timestamps (Phase 4 artifact).

    Returns a DataFrame with a DatetimeIndex and the weather columns, or None
    when the artifact is unavailable. Never forward-filled.
    """
    try:
        df = pd.read_parquet(ml_config.WEATHER_FEATURES_DATA)
    except Exception:  # noqa: BLE001 - weather simply unavailable
        return None
    idx = df["timestamp"] if "timestamp" in df.columns else df.index
    try:
        idx = pd.to_datetime(idx, errors="coerce")
    except (TypeError, ValueError):
        return None
    cols = [c for c in WEATHER_FEATURE_COLS if c in df.columns]
    if not cols:
        return None
    frame = df[cols].copy()
    frame["timestamp"] = idx
    frame = frame.dropna(subset=["timestamp"]).set_index("timestamp")
    if frame.index.tz is not None:
        frame.index = frame.index.tz_localize(None)
    return frame[~frame.index.duplicated(keep="first")]


def _code_to_condition_ordinal(code) -> float:
    """Map a WMO weather code to the ordinal condition used by the models."""
    import weather_features as wf

    try:
        cond = wf.code_to_condition(int(code)) if code is not None else None
    except (TypeError, ValueError):
        cond = None
    if cond is None:
        return float("nan")
    return float(ml_config.WEATHER_CONDITIONS.get(cond, float("nan")))


def _future_weather_frame():
    """Future hourly weather from the persisted Open-Meteo snapshot.

    Returns a DataFrame indexed by timestamp with the weather columns, or None.
    """
    try:
        data = api_cache.load_weather_forecast()
        hourly = data.get("hourly") or {}
        times = pd.to_datetime(hourly.get("time", []))
        if len(times) == 0:
            return None
    except Exception:  # noqa: BLE001 - weather simply unavailable
        return None
    if times.tz is not None:
        times = times.tz_localize(None)
    codes = hourly.get("weather_code") or []
    frame = pd.DataFrame(
        {
            "temperature": pd.to_numeric(hourly.get("temperature_2m"), errors="coerce"),
            "humidity": pd.to_numeric(hourly.get("relative_humidity_2m"), errors="coerce"),
            "precipitation": pd.to_numeric(hourly.get("precipitation"), errors="coerce"),
            "wind_speed": pd.to_numeric(hourly.get("wind_speed_10m"), errors="coerce"),
            "condition": [_code_to_condition_ordinal(c) for c in codes],
        },
        index=times,
    )
    return frame[~frame.index.duplicated(keep="first")]


def _weather_usage(series: pd.Series, days: int, forecast_type: str) -> dict:
    """Decide whether real weather can be used for this forecast.

    Weather is used ONLY when (a) the persisted future weather overlaps the
    forecast period and (b) historical weather covers the uploaded history.
    Otherwise the model falls back to consumption-only and the UI is told so.
    """
    current_date = pd.Timestamp.now(tz=None)
    status = weather_status(series, days, forecast_type, current_date=current_date)
    if status["status"] not in ("full", "partial"):
        return {"used": False, "historical": None, "future": None, "status": status}
    future = _future_weather_frame()
    historical = _historical_weather_frame()
    if future is None or len(future) == 0 or historical is None or len(historical) == 0:
        note = (
            "Weather data is unavailable for this forecast period. "
            "Forecast generated using historical consumption patterns."
        )
        status = {"status": "none", "label": "unavailable", "note": note}
        return {"used": False, "historical": None, "future": None, "status": status}
    # Phase 4.1: track when the weather snapshot was fetched
    snap_result = weather.ensure_snapshot()
    fetched_at = weather.snapshot_fetched_at()
    return {"used": True, "historical": historical, "future": future,
            "status": status, "fetched_at": fetched_at}


# ---------------------------------------------------------------------------
# Horizon
# ---------------------------------------------------------------------------
def resolve_horizon(value: int, unit: str | None) -> dict:
    """Validate a horizon and convert it to days (1..730).

    Units: days = value, months = value*30, years = value*365. Mirrors the
    regional bill engine's horizon conventions for consistency.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadRequestError("horizon_value must be an integer number of days/months/years")
    if value < 1:
        raise BadRequestError("horizon_value must be at least 1")
    key = (unit or "days").strip().lower()
    if key not in HORIZON_UNITS:
        raise BadRequestError(
            f"invalid horizon_unit '{unit}'. Use 'days', 'months' or 'years'."
        )
    factor = [1, 30, 365][HORIZON_UNITS[key]]
    days = value * factor
    if days > api_config.MAX_FORECAST_DAYS:
        raise BadRequestError(
            f"horizon of {value} {unit} = {days} days exceeds the maximum of "
            f"{api_config.MAX_FORECAST_DAYS} days (2 years)."
        )
    if days < api_config.MIN_FORECAST_DAYS:
        raise BadRequestError("horizon must be at least 1 day")
    forecast_type = _forecast_type_for_days(days)
    return {"value": value, "unit": "days" if factor == 1 else "months" if factor == 30 else "years",
            "days": days, "forecast_type": forecast_type}


def _forecast_type_for_days(days: int) -> str:
    if days <= api_config.SHORT_TERM_MAX_DAYS:
        return "short_term"
    if days <= api_config.MEDIUM_TERM_MAX_DAYS:
        return "medium_term"
    return "long_term"


# ---------------------------------------------------------------------------
# Short-term ML model (retrained on the uploaded data)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=api_config.MAX_DATASETS)
def _trained_model(dataset_id: str):
    """Consumption-only XGBoost trained on the uploaded history."""
    return _fit_model(dataset_id, weather=None)


@lru_cache(maxsize=api_config.MAX_DATASETS)
def _trained_weather_model(dataset_id: str):
    """Weather-aware XGBoost: time + lag/rolling + real weather features."""
    return _fit_model(dataset_id, weather=_historical_weather_frame())


def _fit_model(dataset_id: str, weather):
    """Train a lightweight XGBoost on the uploaded history using the existing
    Phase 2 feature recipe, optionally augmented with real weather features.
    Returns (model, feature_names, test_residual_std)."""
    import feature_engineering as fe
    import forecasting as fc

    series = upload_service.get_series(dataset_id)

    if len(series) < 336:
        raise BadRequestError(
            "insufficient historical data for a short-term ML forecast "
            f"({len(series)} rows). At least ~336 rows (2 weeks of hourly data) "
            "are required for the lag/rolling features."
        )

    df = pd.DataFrame({ml_config.CLEANED_COLUMN: series})
    df = fe.add_timestamp_features(df)
    df = fe.add_lag_features(df, ml_config.CLEANED_COLUMN)
    df = fe.add_rolling_features(df, ml_config.CLEANED_COLUMN)

    # Festival/calendar features (Phase 13): joined from the deterministic
    # calendar so the model can learn the household's observed festival pattern.
    festival_frame = festival_calendar.festival_features(df.index)
    for col in FESTIVAL_FEATURE_COLS:
        df[col] = festival_frame[col].to_numpy()

    weather_used: list[str] = []
    if weather is not None and len(weather):
        # Join weather by EXACT timestamp (no lag, no forward fill). Rows whose
        # hour has no observed weather get NaN, which XGBoost treats natively.
        aligned = weather[WEATHER_FEATURE_COLS].reindex(pd.to_datetime(df.index, errors="coerce"))
        weather_used = [c for c in WEATHER_FEATURE_COLS if c in aligned.columns and aligned[c].notna().any()]
        for col in weather_used:
            df[col] = aligned[col].to_numpy()

    feature_cols = [c for c in df.columns if c != ml_config.CLEANED_COLUMN]
    df = df.dropna(subset=["lag_168", "rolling_mean_7d"])
    if len(df) < 400:
        raise BadRequestError(
            "insufficient historical data after feature warm-up for a short-term "
            "ML forecast; a longer history is required."
        )

    # Recent history is the most relevant; cap the training set for speed.
    if len(df) > 150_000:
        df = df.tail(150_000)

    split = int(len(df) * 0.8)
    train, test = df.iloc[:split], df.iloc[split:]
    if len(test) < 2:
        test = train.sample(frac=0.05, random_state=ml_config.RANDOM_STATE)

    model = fc.build_xgboost(params={
        "n_estimators": 250,
        "max_depth": 7,
        "random_state": ml_config.RANDOM_STATE,
    })
    model.fit(train[feature_cols], train[ml_config.CLEANED_COLUMN])
    resid = (test[ml_config.CLEANED_COLUMN] - model.predict(test[feature_cols])).values
    resid_std = float(np.nanstd(resid)) if len(resid) else 0.0
    log.info("short-term model trained for %s (features=%d weather=%s test_n=%d)",
             dataset_id, len(feature_cols), weather_used, len(test))
    return model, feature_cols, resid_std, weather_used


def _short_term_forecast(series: pd.Series, days: int, dataset_id: str,
                         use_weather: bool) -> tuple[pd.Series, float, list[str]]:
    """ML iterated forecast (existing engine) on the uploaded series."""
    from peak_hours import iterated_forecast
    from datetime import datetime, timezone

    if use_weather:
        model, feature_cols, resid_std, weather_used = _trained_weather_model(dataset_id)
        exogenous = _future_weather_frame()
    else:
        model, feature_cols, resid_std, weather_used = _trained_model(dataset_id)
        exogenous = None

    # Calendar feature generators for the iterated engine: each is a callable
    # Timestamp -> number, only emitted when the column is in `feature_names`
    # (so the non-festival Phase 5 path is untouched).
    # Generate festival features from the actual future forecast index so that
    # the _feature_lookup mapping keys match the timestamps used during inference.
    # Previously, features were generated from series.index (historical), causing
    # _get(ts) to always return 0.0 for future timestamps since the timestamps
    # never matched the historical index keys.
    future_start = series.index.max() + pd.Timedelta(hours=1)
    n_periods = days * 24
    future_index = pd.date_range(
        start=future_start, periods=n_periods, freq=ml_config.FREQUENCY
    )
    festival_frame = festival_calendar.festival_features(future_index)
    festival_extras = {
        col: _feature_lookup(festival_frame[col], future_index.min())
        for col in FESTIVAL_FEATURE_COLS
    }

    # The feature recipe operates on hourly lags; the iterated engine emits
    # hourly steps regardless of the uploaded sub-hourly frequency (documented).
    # Build the forecast using the existing engine, then reindex the timestamps
    # to start from the current forecast-generation date (not the historical
    # data end date). This ensures 1-day/7-day/30-day forecasts align with
    # current weather data while the model remains trained on history.
    forecast_native = iterated_forecast(
        series, model, days=days, feature_names=feature_cols, exogenous=exogenous,
        calendar_features=festival_extras)

    # Reindex forecast to start from the current date (not series.index.max())
    # so short-term forecasts align with current weather forecasts.
    # Use direct assignment instead of reindex to avoid NaN when timestamps
    # from iterated_forecast (starting at series.index.max() + 1h) differ
    # from the current-date new_index.
    forecast_start = datetime.now(timezone.utc).replace(tzinfo=None)
    original_start = forecast_native.index.min()
    original_end = forecast_native.index.max()
    n_periods = len(forecast_native)
    # Create new date range from current date for the same number of periods
    new_index = pd.date_range(
        start=forecast_start,
        periods=n_periods,
        freq=forecast_native.index.freq or (original_end - original_start) / n_periods
    )
    forecast = pd.Series(forecast_native.values, index=new_index,
                         name=forecast_native.name)

    return forecast.iloc[: days * 24], resid_std, weather_used


def _feature_lookup(values: pd.Series, first_ts: pd.Timestamp):
    """Build a Timestamp -> value lookup for the festival feature generators."""
    mapping = dict(zip(pd.DatetimeIndex(values.index), values.astype(float).to_numpy()))

    def _get(ts: pd.Timestamp) -> float:
        day = pd.Timestamp(ts).normalize()
        return float(mapping.get(day, 0.0))

    return _get


# ---------------------------------------------------------------------------
# Seasonal / trend model (medium + long term, and non-hourly short term)
# ---------------------------------------------------------------------------
def _native_freq(series: pd.Series, label: str) -> str:
    if label in SUBDAILY:
        mode = series.index.to_series().diff().dropna().mode()
        if len(mode):
            seconds = int(mode.iloc[0].total_seconds())
            if seconds == 1800:
                return "30min"
            if seconds == 900:
                return "15min"
        return "h"
    if label == "daily":
        return "D"
    if label == "weekly":
        return "W"
    if label == "monthly":
        return "MS"
    return "D"


def _seasonal_factors(series: pd.Series, freq_label: str) -> dict:
    """Deterministic trend + seasonality components fitted on the history.

    The slope/intercept are fitted on the *deseasonalized* series (values divided
    by their calendar factors) so the extrapolated trend is anchored to the
    historical level. Fitting the trend on the raw series lets a strong within-year
    cycle manufacture a fictitious slope that drags the forecast below history
    (and LOW-classifies objectively high-consumption datasets).
    """
    y = series.values.astype(float)
    ordinals = (series.index - series.index.min()).total_seconds() / 86400.0
    overall_mean = float(series.mean())

    factors: dict = {"overall_mean": overall_mean}
    if freq_label not in SUBDAILY:
        factors["dow"] = (series.groupby(series.index.dayofweek).mean() / overall_mean).reindex(range(7)).fillna(1.0)
        factors["month"] = (series.groupby(series.index.month).mean() / overall_mean).reindex(range(1, 13)).fillna(1.0)
        seasonal = (
            factors["month"].reindex(series.index.month).to_numpy()
            * factors["dow"].reindex(series.index.dayofweek).to_numpy()
        )
    else:
        factors["month"] = (series.groupby(series.index.month).mean() / overall_mean).reindex(range(1, 13)).fillna(1.0)
        factors["hour"] = (series.groupby(series.index.hour).mean() / overall_mean).reindex(range(24)).fillna(1.0)
        # Dow factor adds little for sub-daily data dominated by hour structure.
        factors["dow"] = None
        seasonal = (
            factors["month"].reindex(series.index.month).to_numpy()
            * factors["hour"].reindex(series.index.hour).to_numpy()
        )

    deseasonalized = y / np.maximum(seasonal, np.finfo(float).eps)
    slope, _ = np.polyfit(ordinals, deseasonalized, 1)
    # Cap the extrapolated trend so a 2-year forecast does not run away.
    max_annual_trend = max(0.0, 0.30 * overall_mean)
    slope = float(np.clip(slope, -max_annual_trend, max_annual_trend))
    # Anchor the trend so it passes through the deseasonalized mean exactly at
    # the midpoint of the history; the forecast level then tracks the uploaded
    # household's true baseline instead of being biased low.
    anchor = float(np.mean(deseasonalized))
    intercept = anchor - slope * float(np.mean(ordinals))
    factors["slope"] = slope
    factors["intercept"] = intercept
    return factors


def _seasonal_predict(series: pd.Series, factors: dict, future: pd.DatetimeIndex) -> pd.Series:
    """Apply trend + seasonality to future timestamps."""
    ordinals = (future - series.index.min()).total_seconds() / 86400.0
    trend = factors["intercept"] + factors["slope"] * ordinals
    pred = pd.Series(trend, index=future, dtype=float)
    month = factors.get("month")
    hour = factors.get("hour")
    dow = factors.get("dow")
    if month is not None:
        pred = pred * month.reindex(future.month).to_numpy()
    if hour is not None:
        pred = pred * hour.reindex(future.hour).to_numpy()
    if dow is not None:
        pred = pred * dow.reindex(future.dayofweek).to_numpy()
    return pred.clip(lower=0.0)


def _seasonal_residual_std(series: pd.Series, factors: dict, freq_label: str) -> float:
    """Residual std of the seasonal-trend fit on the in-sample history."""
    future = pd.DatetimeIndex(pd.date_range(
        start=series.index.min(), end=series.index.max(), freq=_native_freq(series, freq_label)))
    fitted = _seasonal_predict(series, factors, future)
    aligned = fitted.reindex(series.index).fillna(series.mean())
    resid = (series.values - aligned.values).astype(float)
    return float(np.nanstd(resid)) if len(resid) else 0.0


def _seasonal_forecast(series: pd.Series, days: int, freq_label: str) -> tuple[pd.Series, float]:
    """Generate a native-frequency forecast for `days` using the seasonal model."""
    factors = _seasonal_factors(series, freq_label)
    freq = _native_freq(series, freq_label)
    if freq in ("W",):
        periods = days // 7 + 1
        start = series.index.max() + pd.Timedelta(days=7)
    elif freq == "MS":
        periods = max(1, days // 30 + 1)
        start = (series.index.max() + pd.DateOffset(months=1)).normalize()
    elif freq == "D":
        periods = days
        start = series.index.max() + pd.Timedelta(days=1)
    else:  # sub-daily
        mode = series.index.to_series().diff().dropna().mode()
        td = mode.iloc[0] if len(mode) else pd.Timedelta(hours=1)
        periods = days * int(pd.Timedelta(days=1) / td)
        start = series.index.max() + td
    future = pd.date_range(start=start, periods=periods, freq=freq)
    pred = _seasonal_predict(series, factors, future)
    resid_std = _seasonal_residual_std(series, factors, freq_label)
    return pred, resid_std


# ---------------------------------------------------------------------------
# Aggregation for display
# ---------------------------------------------------------------------------
def display_granularity(forecast_type: str, days: int, freq_label: str) -> str:
    """Pick an aggregated display frequency so we never dump thousands of points.

    Short-term sub-daily forecasts keep their native frequency (24–168 points);
    longer horizons aggregate to daily / weekly / monthly per spec section 16.
    """
    if forecast_type == "short_term":
        return freq_label
    if days <= 30:
        return "daily"
    if days <= api_config.MEDIUM_TERM_MAX_DAYS:
        return "weekly"
    return "monthly"


def _aggregate(series: pd.Series, granularity: str) -> pd.Series:
    """Bucket sums (energy per display period) for visualization."""
    if granularity in SUBDAILY:
        if granularity != "hourly":
            return series
        return series
    rule = {"daily": "D", "weekly": "W", "monthly": "ME"}[granularity]
    return series.resample(rule).sum()


def _native_counts(series: pd.Series, granularity: str) -> np.ndarray:
    """Number of native steps that fall into each display bucket."""
    if granularity in SUBDAILY:
        return np.ones(len(series), dtype=int)
    rule = {"daily": "D", "weekly": "W", "monthly": "ME"}[granularity]
    counts = series.resample(rule).count()
    return counts.to_numpy()


def _trim_partial_edges(counts: np.ndarray) -> np.ndarray:
    """Boolean mask keeping only buckets that cover a full aggregate period.

    Weekly/monthly resampling of a horizon that starts/ends mid-period produces
    partial edge buckets (e.g. a 24 h ``month``). Those distort means and
    percentiles, so classification diagnostics are computed on the full buckets.
    """
    mask = np.ones(len(counts), dtype=bool)
    if len(counts) >= 2:
        interior = counts[1:-1] if len(counts) > 2 else counts[1:]
        full_ref = float(interior.max()) if len(interior) else float(counts[1])
        # Only edges are ever partial, so only ever trim first/last.
        if float(counts[0]) < 0.8 * full_ref:
            mask[0] = False
        if len(counts) > 1 and float(counts[-1]) < 0.8 * full_ref:
            mask[-1] = False
    return mask


# ---------------------------------------------------------------------------
# Weather status (honest availability check)
# ---------------------------------------------------------------------------
_LONG_TERM_WEATHER_NOTE = (
    "Long-term forecast uses historical weather relationships and seasonal "
    "patterns. Exact future weather is not available at this horizon."
)


def weather_status(series: pd.Series, days: int, forecast_type: str,
                   current_date: pd.Timestamp | None = None) -> dict:
    """Report how much of the forecast period real future weather covers."""
    if forecast_type == "long_term":
        return {"status": "not_available", "label": "long-term historical pattern",
                "note": _LONG_TERM_WEATHER_NOTE}
    try:
        data = api_cache.load_weather_forecast()
        hourly = data.get("hourly") or {}
        times = pd.to_datetime(hourly.get("time", []))
        if len(times) == 0:
            raise FileNotFoundError
    except Exception:  # noqa: BLE001 - weather simply unavailable
        return {"status": "none", "label": "unavailable",
                "note": "No future weather data is available for the forecast period; the model uses only the uploaded history."}

    wmin, wmax = times.min(), times.max()
    if current_date is None:
        current_date = series.index.max()
    fstart, fend = current_date, current_date + pd.Timedelta(days=days)
    if fstart > wmax or fend < wmin:
        return {"status": "none", "label": "unavailable",
                "note": "Future weather data does not overlap the forecast period; the model uses only the uploaded history."}
    overlap = max(pd.Timedelta(0), min(fend, wmax) - max(fstart, wmin)) / pd.Timedelta(days=max(1, days))
    if overlap >= 0.95:
        status, label = "full", "available"
        note = "Weather-aware forecast: future weather is available and can be used for this period."
    elif overlap >= 0.05:
        status, label = "partial", "partially available"
        note = "Weather-aware forecast: only part of the forecast period overlaps the available weather data."
    else:
        status, label = "none", "unavailable"
        note = "No future weather data is available for the forecast period; the model uses only the uploaded history."
    return {"status": status, "label": label, "note": note}


def _weather_block(status: dict, forecast_type: str, weather_used: list[str],
                   fetched_at: str | None = None) -> dict:
    """Phase 4.1 weather metadata block.

    Additive on top of the existing ``{status,label,note}`` shape so the UI and
    the AI assistant can always see: whether weather was available/used, its
    source, the exact features that entered the model, a human note and the raw
    status string. ``weather_available`` is strictly honest — it is True only
    when real weather (or, for long horizons, historical/seasonal patterns)
    informs the forecast, never fabricated overlap.
    """
    status_val = status.get("status")
    is_long_term = forecast_type == "long_term"
    used_features = [f for f in (weather_used or []) if f]
    source: str | None
    if status_val in ("full", "partial"):
        source = "Open-Meteo"
        available = True
    elif is_long_term:
        source = "Open-Meteo (historical/seasonal patterns)"
        available = True
    else:
        source = None
        available = False
    return {
        **status,
        "weather_status": status_val,
        "weather_available": available,
        "weather_source": source,
        "weather_features_used": used_features,
        "weather_note": status.get("note"),
        "weather_fetched_at": fetched_at,
    }


# ---------------------------------------------------------------------------
# Household bill (existing deterministic engine, household scope only)
# ---------------------------------------------------------------------------
def household_bill_estimate(scope: str, unit: str, total_energy: float, days: int,
                            tariff: str | None) -> dict | None:
    """Estimate a monthly household bill from the forecasted total energy using
    the existing backend billing engine. Household scope + kWh only; regional
    datasets are never priced as household bills."""
    if scope != ml_config.SCOPE_HOUSEHOLD or unit not in ("kWh", "KW", "kw"):
        return None
    months = max(1.0, days / 30.0)
    if total_energy <= 0:
        monthly_kwh = 0.0
    else:
        monthly_kwh = total_energy / months
    import household_bills as hb

    try:
        t = hb.load_household_tariff(tariff)
    except hb.HouseholdTariffError as exc:
        raise BadRequestError(str(exc)) from exc
    bill = hb.compute_household_bill(monthly_kwh, t)
    bill["forecasted_period"] = f"next {days} days"
    bill["forecasted_monthly_kwh"] = round(monthly_kwh, 3)
    return bill


# ---------------------------------------------------------------------------
# Shared forecast runner
# ---------------------------------------------------------------------------
@lru_cache(maxsize=api_config.MAX_DATASETS)
def _run(dataset_id: str, horizon_value: int, horizon_unit: str, scope_override: str | None) -> dict:
    """Cached full forecast generation for one (dataset, horizon, scope) triple."""
    meta = upload_service.get_metadata(dataset_id)
    series = upload_service.get_series(dataset_id)
    horizon = resolve_horizon(horizon_value, horizon_unit)
    days = horizon["days"]
    forecast_type = horizon["forecast_type"]
    freq_label = meta["frequency"]["label"]

    # Strategy: ML for sub-daily short term; seasonal otherwise. Weather features
    # are added to the ML model ONLY when real future + historical weather
    # overlaps the uploaded data (see _weather_usage).
    use_ml = freq_label in SUBDAILY and forecast_type == "short_term"
    weather_usage = _weather_usage(series, days, forecast_type)
    weather = weather_usage["status"]
    use_weather_features = bool(use_ml and weather_usage["used"])
    if use_ml:
        forecast_native, resid_std, weather_used = _short_term_forecast(
            series, days, dataset_id, use_weather_features)
    else:
        forecast_native, resid_std = _seasonal_forecast(series, days, freq_label)
        weather_used = []

    granularity = display_granularity(forecast_type, days, freq_label)

    # Phase 13 — festival/calendar block. Calendar facts + the household's own
    # observed festival effects (only when sufficient history exists). On the
    # seasonal path we apply the observed effect inside future festival windows;
    # on the ML path the festival features were already in the feature matrix,
    # so nothing is double-applied here.
    festival_analysis = festival_calendar.analyze_historical_festivals(series)
    current_date = pd.Timestamp.now(tz=None)
    festival_upcoming = festival_calendar.upcoming_festivals(
        current_date, days, festival_analysis)
    festival_applied: list[dict] = []
    if not use_ml:
        forecast_native, festival_applied = festival_calendar.adjust_forecast(
            forecast_native, festival_upcoming)
    festivals = festival_calendar.festivals_payload(
        series, days, weather_used=bool(use_weather_features),
        forecast_type=forecast_type,
        weather_status=weather.get("status"),
        weather_source=weather.get("label"),
        weather_features_used=weather_used,
        weather_fetched_at=weather_usage.get("fetched_at"),
    )
    # Keep the *actually applied* adjustments discoverable in the payload.
    festivals["applied"] = festival_applied
    festivals["weather_available"] = bool(use_weather_features)

    scope_info = meta["scope"]
    if scope_override in ("household", "regional_grid"):
        scope_info = {**scope_info, "scope": scope_override,
                      "unit": "kWh" if scope_override == "household" else "MW",
                      "detected_by": "user_override"}
    scope = scope_info["scope"]
    unit = scope_info["unit"]

    # Display-scale aggregation (bucket sums) + bounds from residual std.
    display = _aggregate(forecast_native, granularity)
    counts = _native_counts(forecast_native, granularity)
    resid = resid_std if _finite(resid_std) else 0.0
    intervals_available = _finite(resid_std) and resid_std > 0
    band = Z_MULT * resid * np.sqrt(np.maximum(counts, 1))
    band = np.where(intervals_available, band, 0.0)
    if not intervals_available:
        band = np.zeros(len(display))

    # Historical baseline aggregated to the SAME display form (bucket sums as
    # energy per period), used for classification thresholds so the two are always
    # scale-consistent with the displayed forecast points.
    hist_display = _aggregate(series, granularity)

    # Explainable classification diagnostics — all scale-consistent to the
    # displayed buckets (historical + forecast compared in the same form).
    # For weekly/monthly horizons the resample may create partial edge buckets
    # (e.g. a 24 h "month"); the baselines and thresholds compare only full
    # periods so neither ever gets distorted by a boundary artifact.
    hist_counts = _native_counts(series, granularity)
    forecast_counts = _native_counts(forecast_native, granularity)
    mask = _trim_partial_edges(hist_counts)[: len(hist_display)]
    fmask = _trim_partial_edges(forecast_counts)[: len(display)]
    hist_stat = hist_display[mask] if granularity not in SUBDAILY else hist_display
    disp_stat = display[fmask] if granularity not in SUBDAILY else display
    if len(hist_stat) == 0:
        hist_stat = hist_display
    if len(disp_stat) == 0:
        disp_stat = display

    # Classification from percentiles of the uploaded history at the forecast's
    # display granularity (e.g. daily forecasts vs historical daily-energy
    # percentiles) — never arbitrary fixed thresholds.
    thresholds = thresholds_from_history(
        hist_stat, api_config.LOW_PERCENTILE, api_config.HIGH_PERCENTILE)
    labels = classify_values(display.to_numpy(), thresholds)
    class_summary = classification_summary(display.to_numpy(), thresholds)

    hist_stat_mean = float(hist_stat.mean()) if len(hist_stat) else 0.0
    disp_stat_mean = float(disp_stat.mean()) if len(disp_stat) else 0.0
    diag_change_percent = (
        round((disp_stat_mean - hist_stat_mean) / abs(hist_stat_mean) * 100.0, 2)
        if hist_stat_mean else 0.0
    )
    historical_mean = round(hist_stat_mean, 3)
    forecast_mean = round(disp_stat_mean, 3)
    hist_values = hist_stat.dropna().to_numpy(dtype=float)
    forecast_values = disp_stat.dropna().to_numpy(dtype=float)
    historical_p90 = round(float(np.percentile(hist_values, 90.0)), 3) if len(hist_values) else 0.0
    high_period_count = int(np.sum(forecast_values >= historical_p90))
    high_period_percentage = round(high_period_count / max(1, len(forecast_values)) * 100.0, 2)
    forecast_peak_value = round(float(display.max()), 3) if len(display) else 0.0
    status_label = classify_value(forecast_mean, thresholds)
    reason = _classification_reason(
        status_label, forecast_mean, historical_mean, diag_change_percent,
        high_period_count, len(forecast_values), unit, granularity)
    warning = None
    if diag_change_percent <= -api_config.TREND_STABLE_THRESHOLD_PCT:
        warning = (
            f"The forecast average ({forecast_mean} {unit}) is significantly below the "
            f"uploaded historical baseline ({historical_mean} {unit}, change "
            f"{diag_change_percent}%). This is a forecast-model diagnostic: compare the "
            "chart with your own history rather than treating the period as low "
            "consumption."
        )

    summary = {
        "average": round(float(display.mean()), 3),
        "minimum": round(float(display.min()), 3),
        "maximum": round(float(display.max()), 3),
        "total": round(float(display.sum()), 3),
        "change_percent": diag_change_percent,
        "high_periods": int(class_summary["counts"]["HIGH"]),
        "medium_periods": int(class_summary["counts"]["MEDIUM"]),
        "low_periods": int(class_summary["counts"]["LOW"]),
        "periods": int(len(display)),
        "granularity": granularity,
    }

    # Peak analysis (adapted to display granularity).
    display_safe = display.dropna()
    if len(display_safe) == 0:
        peak_label = None
        peak = {
            "timestamp": None,
            "value": 0.0,
            "peak_hour": None,
            "peak_time_label": None,
            "average": summary["average"],
            "peak_to_average_ratio": 0.0,
        }
    else:
        peak_label = display_safe.idxmax()
        peak_ts = pd.Timestamp(peak_label)
        peak = {
            "timestamp": str(peak_ts),
            "value": round(float(display.max()), 3),
            "peak_hour": int(peak_ts.hour) if granularity in SUBDAILY else None,
            "peak_time_label": _peak_time_label(peak_ts, granularity),
            "average": summary["average"],
            "peak_to_average_ratio": round(float(display.max() / display.mean()), 3)
            if display.mean() else 0.0,
        }

    # Per-point weather attachment for sub-daily displays (used by CSV export
    # and the UI). Only ever real values from the persisted forecast.
    future_weather = weather_usage["future"]
    point_weather: dict = {}
    if granularity in SUBDAILY and future_weather is not None and len(future_weather):
        point_weather = {ts: future_weather.loc[ts] for ts in display.index if ts in future_weather.index}

    def _point_weather(ts):
        row = point_weather.get(ts)
        if row is None:
            return False, None, None
        temp = row.get("temperature")
        hum = row.get("humidity")
        return True, (
            round(float(temp), 1) if _finite(temp) else None
        ), (
            round(float(hum), 1) if _finite(hum) else None
        )

    points = []
    point_festivals = festival_calendar.festival_features(display.index)
    for i, (ts, v) in enumerate(display.items()):
        w_avail, w_temp, w_hum = _point_weather(ts)
        festival_row = point_festivals.loc[ts] if ts in point_festivals.index else None
        points.append({
            "timestamp": str(ts),
            "predicted_consumption": round(float(v), 3),
            "lower_bound": round(float(v) - band[i], 3) if intervals_available else None,
            "upper_bound": round(float(v) + band[i], 3) if intervals_available else None,
            "classification": labels[i],
            "peak_flag": peak_label is not None and bool(ts == peak_ts),
            "weather_available": w_avail,
            "temperature": w_temp,
            "humidity": w_hum,
            "is_festival": bool(festival_row["is_festival"]) if festival_row is not None else False,
            "festival_name": str(festival_row["festival_name"]) if festival_row is not None and festival_row["is_festival"] else None,
            "is_holiday": bool(festival_row["is_holiday"]) if festival_row is not None else False,
        })

    # Historical tail at the same display granularity (bucket sums) so the
    # chart can show where history ends and the forecast begins.
    historical_tail = [
        {"timestamp": str(ts), "value": round(float(v), 3)}
        for ts, v in hist_display.tail(120).items()
    ]

    evening_share = (
        evening_demand_share(display.to_numpy(), display.index, 17, 22)
        if granularity in SUBDAILY else None
    )
    projected_annual_growth = None
    if forecast_type == "long_term":
        projected_annual_growth = _annual_growth_from_history(series, days)

    recommendations = generate_recommendations(
        counts=class_summary["counts"],
        change_percent=diag_change_percent,
        peak_to_average_ratio=peak["peak_to_average_ratio"],
        evening_share=evening_share,
        forecast_type=forecast_type,
        projected_annual_growth_pct=projected_annual_growth,
        festival_upcoming=festivals["upcoming"],
    )

    bill = household_bill_estimate(scope, unit, summary["total"], days, None)

    view = _granularity_view(granularity)
    return {
        "dataset_id": dataset_id,
        "filename": meta["filename"],
        "horizon": {"value": horizon_value,
                    "unit": "days" if horizon_unit in ("days", "day") else "months" if horizon_unit in ("months", "month") else "years",
                    "days": days},
        "forecast_type": forecast_type,
        "forecast_type_label": _forecast_type_label(forecast_type),
        "display_label": _display_label(horizon_value, horizon_unit, view),
        "unit": unit,
        "energy_unit": meta["energy_unit"] if scope == "regional_grid" else "kWh",
        "scope": scope,
        "scope_detected_by": scope_info["detected_by"],
        "display_granularity": granularity,
        "model": _model_label(use_ml, weather_used),
        "model_features": _features_summary(use_ml, weather_used),
        "trend": _trend_label(diag_change_percent),
        "status": status_label,
        "warning": warning,
        "summary": summary,
        "classification": {
            **class_summary,
            "thresholds": {
                "low": thresholds["low_threshold"],
                "high": thresholds["high_threshold"],
            },
            "note": (
                "Thresholds are the 33rd/66th percentiles of the uploaded "
                "historical consumption distribution."
            ),
            "historical_mean": historical_mean,
            "forecast_mean": forecast_mean,
            "forecast_change_percent": diag_change_percent,
            "historical_90th_percentile": historical_p90,
            "high_period_count": high_period_count,
            "high_period_percentage": high_period_percentage,
            "forecast_peak": forecast_peak_value,
            "status": status_label,
            "reason": reason,
            "warning": warning,
        },
        "peak": peak,
        "points": points,
        "historical": historical_tail,
        "intervals_available": intervals_available,
        "weather": _weather_block(weather, forecast_type, weather_used,
                                  weather_usage.get("fetched_at")),
        "recommendations": recommendations,
        "festivals": festivals,
        "household_bill": bill,
        "generated_at": api_cache.utc_now(),
    }


def _finite(value: float) -> bool:
    return bool(np.isfinite(value))


def _peak_time_label(ts: pd.Timestamp, granularity: str) -> str:
    if granularity in SUBDAILY:
        return f"{ts.hour:02d}:00 (hour of day {ts.hour})"
    if granularity == "daily":
        return str(ts.date())
    if granularity == "weekly":
        return f"week of {str(ts.date())}"
    return ts.strftime("%Y-%m")


def _forecast_type_label(forecast_type: str) -> str:
    if forecast_type == "short_term":
        return "Short-term (1–7 days)"
    if forecast_type == "medium_term":
        return "Medium-term (8 days – 6 months)"
    return "Long-term (6 months – 2 years)"


def _granularity_view(granularity: str) -> str:
    """User-facing name of the forecast resolution (never over-promises)."""
    return {
        "hourly": "hourly",
        "30min": "30-minute",
        "15min": "15-minute",
        "minutely": "minutely",
        "daily": "daily",
        "weekly": "weekly",
        "monthly": "monthly",
    }.get(granularity, granularity)


def _display_label(horizon_value: int, horizon_unit: str, view: str) -> str:
    """e.g. \"2 Year Forecast — monthly view\" / \"30 Day Forecast — daily view\"."""
    unit_word = {"days": "Day", "day": "Day", "months": "Month", "month": "Month",
                 "years": "Year", "year": "Year"}.get(horizon_unit, horizon_unit)
    return f"{horizon_value} {unit_word} Forecast — {view} view"


def _model_label(use_ml: bool, weather_used: list[str]) -> str:
    if not use_ml:
        return "Seasonal + trend"
    if weather_used:
        return "XGBoost + time/weather features"
    return "XGBoost + time features"


def _features_summary(use_ml: bool, weather_used: list[str]) -> list[str]:
    if not use_ml:
        return ["historical consumption", "day of week", "month", "linear trend"]
    features = [
        "historical consumption", "hour", "day of week", "day of month",
        "month", "year", "weekend", "lag & rolling history features",
        "festival/calendar features",
    ]
    features.extend(w.replace("_", " ") for w in weather_used)
    return features


def _trend_label(change_percent: float) -> str:
    """Trend vs the historical baseline within a configurable stable band.

    The comparison is household-relative (the uploaded history), and the band
    defaults to ±10% (configurable via TREND_STABLE_THRESHOLD_PCT).
    """
    band = api_config.TREND_STABLE_THRESHOLD_PCT
    if change_percent > band:
        return "INCREASING"
    if change_percent < -band:
        return "DECREASING"
    return "STABLE"


def _classification_reason(status: str, forecast_mean: float, historical_mean: float,
                           change_percent: float, high_period_count: int,
                           n_periods: int, unit: str, granularity: str) -> str:
    """Human-readable, numeric explanation of the consumption classification.

    Always household-relative: every figure comes from this dataset's own
    forecast and uploaded history (never fixed universal thresholds).
    """
    view = _granularity_view(granularity)
    if high_period_count and n_periods:
        high_part = (
            f"{high_period_count} of {n_periods} predicted "
            f"{view} periods ({round(high_period_count / n_periods * 100.0, 1)}%) "
            "are at or above the household's historical 90th percentile."
        )
    else:
        high_part = "no predicted periods exceed the household's historical 90th percentile."
    base = (
        f"Forecast average {forecast_mean} {unit} vs historical average "
        f"{historical_mean} {unit} ({change_percent:+.1f}%)."
    )
    if status == "HIGH":
        return (
            f"Forecast consumption is significantly above the household historical "
            f"baseline. {base} {high_part}"
        )
    if status == "LOW":
        return (
            f"Forecast consumption is below the household historical baseline. "
            f"{base} {high_part}"
        )
    return (
        f"Forecast consumption is in line with the household historical baseline. "
        f"{base} {high_part}"
    )


def _annual_growth_from_history(series: pd.Series, days: int) -> float | None:
    """Annualized growth (%) from the deseasonalized history trend.

    Uses the same deseasonalized fit as ``_seasonal_factors`` so a strong
    within-year cycle never masquerades as genuine year-on-year growth.
    """
    factors = _seasonal_factors(series, "daily")
    try:
        slope = factors["slope"]
    except (TypeError, ValueError):
        return None
    mean = float(series.mean())
    if not mean:
        return None
    growth = slope * 365.0 / mean * 100.0
    return round(float(growth), 2)


def generate(dataset_id: str, horizon_value: int, horizon_unit: str | None,
             scope: str | None = None) -> dict:
    """Public generate() entry point (used by routes + tests)."""
    upload_service.get_metadata(dataset_id)  # raises NotFound if unknown
    weather.ensure_snapshot()  # Phase 4.1: best-effort auto-refresh, never blocks
    return _run(dataset_id, horizon_value, horizon_unit or "days", scope)


def export_csv(payload: dict) -> str:
    """CSV of the forecast points (timestamp, predicted, bounds, classification)."""
    out = io.StringIO()
    writer = _csv_writer(out)
    writer.writerow(["timestamp", "predicted_consumption", "lower_bound", "upper_bound", "classification",
                     "peak_flag", "weather_available", "temperature", "humidity"])
    for p in payload["points"]:
        writer.writerow([
            p["timestamp"],
            p["predicted_consumption"],
            "" if p["lower_bound"] is None else p["lower_bound"],
            "" if p["upper_bound"] is None else p["upper_bound"],
            p["classification"],
            "yes" if p.get("peak_flag") else "",
            "yes" if p.get("weather_available") else "",
            "" if p.get("temperature") is None else p["temperature"],
            "" if p.get("humidity") is None else p["humidity"],
        ])
    return out.getvalue()


def export_summary(payload: dict) -> str:
    """Optional compact summary export."""
    out = io.StringIO()
    writer = _csv_writer(out)
    writer.writerow(["--", "Forecast summary"])
    writer.writerow(["file", payload.get("filename", "")])
    writer.writerow(["horizon", f"{payload['horizon']['value']} {payload['horizon']['unit']}"])
    writer.writerow(["forecast_type", payload["forecast_type"]])
    writer.writerow(["unit", payload["unit"]])
    writer.writerow(["average", payload["summary"]["average"]])
    writer.writerow(["total", payload["summary"]["total"]])
    writer.writerow(["peak", payload["peak"]["value"]])
    writer.writerow(["peak_timestamp", payload["peak"]["timestamp"]])
    writer.writerow(["change_percent", payload["summary"]["change_percent"]])
    writer.writerow(["low_threshold", payload["classification"]["thresholds"]["low"]])
    writer.writerow(["high_threshold", payload["classification"]["thresholds"]["high"]])
    return out.getvalue()


def _csv_writer(out):
    import csv

    return csv.writer(out)