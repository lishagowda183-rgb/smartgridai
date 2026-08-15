"""Phase 5: peak-hour analysis for the hourly electricity-consumption series.

Identifies historical peak hours, the average consumption profile by hour of
day, maximum demand, the peak-to-average ratio, morning / evening peak bands,
the top historical peak periods, and -- using an iterated multi-step forecast
from the best trained consumption-only model -- predicted future peak periods.

Pure functions operate on a datetime-indexed `pd.Series` and are unit-testable
on small synthetic inputs. ``main()`` persists:

  * ml/data/processed/peak_analysis.json -> full report
  * ml/data/processed/peak_hours_plot.png -> by-hour profile + forecast bands
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

import joblib
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import config  # noqa: E402
import feature_engineering as fe  # noqa: E402
import forecasting  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("peak_hours")


def average_by_hour(series: pd.Series) -> pd.DataFrame:
    """Mean / median / std / count of consumption for each hour of day (0-23)."""
    grouped = pd.DataFrame({"hour": series.index.hour, "value": series.values})
    stats = (
        grouped.groupby("hour")["value"]
        .agg(["mean", "median", "std", "count"])
        .rename(columns={"mean": "mean_consumption", "median": "median_consumption"})
        .round(2)
    )
    return stats.reindex(range(24)).fillna(0.0)


def peak_hour_of_day(by_hour: pd.DataFrame) -> int:
    """Hour of day with the highest mean consumption."""
    return int(by_hour["mean_consumption"].idxmax())


def max_demand(series: pd.Series) -> dict:
    """Global maximum demand: timestamp + value."""
    ts = series.idxmax()
    return {"timestamp": str(ts), "value": round(float(series.max()), 2)}


def peak_to_average_ratio(series: pd.Series) -> float:
    """Ratio of the maximum demand to the overall mean consumption."""
    return round(float(series.max() / series.mean()), 2)


def windowed_peaks(series: pd.Series, start_hour: int, end_hour: int, name: str) -> pd.DataFrame:
    """Per-day maximum consumption within the [start_hour, end_hour] window."""
    mask = (series.index.hour >= start_hour) & (series.index.hour <= end_hour)
    db = pd.DataFrame({"date": series.index.date, "value": series.values})[mask]
    peak = db.groupby("date")["value"].max().rename(name)
    return peak.to_frame().reset_index()


def morning_peaks(series: pd.Series) -> pd.DataFrame:
    """Per-day maximum consumption within the morning window."""
    return windowed_peaks(
        series, config.MORNING_START_HOUR, config.MORNING_END_HOUR, "morning_peak"
    )


def evening_peaks(series: pd.Series) -> pd.DataFrame:
    """Per-day maximum consumption within the evening window."""
    return windowed_peaks(
        series, config.EVENING_START_HOUR, config.EVENING_END_HOUR, "evening_peak"
    )


def detect_peak_periods(
    series: pd.Series, percentile: float = config.PEAK_PERCENTILE
) -> pd.DataFrame:
    """Contiguous runs of hours at/above `percentile` of historical values.

    Returns one row per period: start, end, duration (hours), peak value and
    the mean consumption across the period.
    """
    threshold = float(np.nanpercentile(series.values, percentile))
    above = (series >= threshold).to_numpy()
    periods: list[dict] = []
    run_start: int | None = None
    for i, flag in enumerate(above):
        if flag and run_start is None:
            run_start = i
        elif not flag and run_start is not None:
            periods.append((run_start, i - 1))
            run_start = None
    if run_start is not None:
        periods.append((run_start, len(series) - 1))

    rows = []
    for start, end in periods:
        chunk = series.iloc[start : end + 1]
        rows.append(
            {
                "start": str(chunk.index.min()),
                "end": str(chunk.index.max()),
                "duration_hours": int(len(chunk)),
                "peak_value": round(float(chunk.max()), 2),
                "mean_value": round(float(chunk.mean()), 2),
            }
        )
    rows.sort(key=lambda r: r["peak_value"], reverse=True)
    return pd.DataFrame(rows)


def iterated_forecast(
    series: pd.Series,
    model,
    days: int = config.PEAK_FORECAST_DAYS,
    feature_names: list[str] | None = None,
    exogenous: "pd.DataFrame | None" = None,
    calendar_features: "dict[str, object] | None" = None,
) -> pd.Series:
    """Multi-step forecast beyond the series end using an iterated strategy.

    Builds the 21-column Phase 3/4 feature matrix one hour at a time: lags and
    rolling means are filled from the observed (history) and already predicted
    (forecast) values; timestamp features come from the calendar. Returns a
    series of predicted consumption for the next `days * 24` hours.

    ``feature_names`` may be supplied when forecasting an arbitrary uploaded
    series (``user_forecast`` retrains the same feature recipe on the user's
    data). When omitted (default) the Phase 3/4 feature columns are loaded from
    the persisted feature artifact — retaining the original Phase 5/6/7 behavior.

    ``exogenous`` is an optional DataFrame indexed by the future timestamps with
    extra columns (e.g. weather) that appear in ``feature_names``. Values are
    injected per forecast step by exact timestamp; missing rows yield NaN, which
    XGBoost treats natively. Never used to fabricate data.

    ``calendar_features`` is an optional dict {feature_name: callable} where each
    callable receives a future ``pd.Timestamp`` and returns a number. Its keys
    are injected per step only when they also occur in ``feature_names`` (default
    None keeps the regional Phase 5/6/7 path byte-for-byte unchanged; the Phase 3
    festival-aware user forecast passes festival/calendar features here).

    Returns a Series of predicted consumption for the next ``days * 24`` hours.
    """
    if feature_names is None:
        feature_names = forecasting.feature_columns(forecasting.load_features())
    if "split" in feature_names:
        feature_names.remove("split")

    n = len(series)
    window = np.concatenate([series.values, np.full(days * 24, np.nan)])
    future = pd.date_range(start=series.index.max() + pd.Timedelta(hours=1), periods=days * 24, freq=config.FREQUENCY)

    predicted: list[float] = []
    for k in range(days * 24):
        t = future[k]
        idx = n + k
        features = {
            "hour": t.hour,
            "day": t.day,
            "day_of_week": t.dayofweek,
            "day_of_month": t.day,
            "week_of_year": int(t.isocalendar().week),
            "month": t.month,
            "quarter": t.quarter,
            "year": t.year,
            "is_weekend": int(t.dayofweek >= 5),
        }
        if calendar_features is not None:
            for col, fn in calendar_features.items():
                if col in feature_names and col not in features:
                    features[col] = float(fn(t))
        for hours in config.LAG_HOURS:
            features[f"lag_{hours}"] = window[idx - hours]
        for hours in config.ROLLING_HOURS:
            col = config.rolling_feature_name(hours)
            values = window[idx - hours : idx]
            features[col] = float(np.nanmean(values))
        if exogenous is not None and len(exogenous) > 0:
            if t in exogenous.index:
                row = exogenous.loc[t]
                for col in exogenous.columns:
                    if col in feature_names and col not in features:
                        features[col] = row[col]
            else:
                for col in exogenous.columns:
                    if col in feature_names and col not in features:
                        features[col] = float("nan")
        X = pd.DataFrame([features])[feature_names]
        y = float(model.predict(X)[0])
        predicted.append(y)
        window[idx] = y

    return pd.Series(predicted, index=future, name=config.CLEANED_COLUMN)


def build_report() -> dict:
    """Assemble and persist the peak-analysis report + plot."""
    config.ensure_dirs()
    df = forecasting.load_features()
    series = df[config.CLEANED_COLUMN]
    by_hour = average_by_hour(series)
    max_dem = max_demand(series)
    p2a = peak_to_average_ratio(series)
    morning = morning_peaks(series)
    evening = evening_peaks(series)
    periods = detect_peak_periods(series)

    model_path = config.PEAK_FORECAST_MODEL
    if not model_path.exists():
        raise FileNotFoundError(
            f"{model_path} missing. Run `python ml/scripts/train_weather_models.py` first."
        )
    model = joblib.load(model_path)
    forecast = iterated_forecast(series, model, days=config.PEAK_FORECAST_DAYS)
    forecast_periods = detect_peak_periods(forecast, percentile=config.PEAK_PERCENTILE)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "series": {
            "rows": int(len(series)),
            "start": str(series.index.min()),
            "end": str(series.index.max()),
        },
        "peak_definition": {
            "percentile": config.PEAK_PERCENTILE,
            "morning_window": f"{config.MORNING_START_HOUR}-{config.MORNING_END_HOUR}",
            "evening_window": f"{config.EVENING_START_HOUR}-{config.EVENING_END_HOUR}",
        },
        "summary": {
            "peak_hour_of_day": peak_hour_of_day(by_hour),
            "max_demand": max_dem,
            "peak_to_average_ratio": p2a,
        },
        "average_by_hour": by_hour.reset_index().to_dict(orient="records"),
        "morning_peak_days": min(len(morning), 10),
        "evening_peak_days": min(len(evening), 10),
        "top_historical_peak_periods": periods.head(10).to_dict(orient="records"),
        "forecast": {
            "model": str(model_path),
            "horizon_days": config.PEAK_FORECAST_DAYS,
            "start": str(forecast.index.min()),
            "end": str(forecast.index.max()),
            "predicted_future_peak_periods": forecast_periods.head(10).to_dict(orient="records"),
        },
    }

    config.PEAK_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("Peak report written to %s", config.PEAK_REPORT)
    build_plot(by_hour, series, forecast, config.PEAK_PLOT)
    return report


def build_plot(by_hour: pd.DataFrame, series: pd.Series, forecast: pd.Series,
               dest) -> None:
    """Two-panel figure: by-hour mean profile + actual vs forecast (test end)."""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9))

    hours = by_hour.index
    ax1.bar(hours, by_hour["mean_consumption"], color="#ff7f0e", width=0.7)
    ax1.axvline(config.MORNING_START_HOUR - 0.5, color="gray", ls="--", lw=0.8)
    ax1.axvline(config.MORNING_END_HOUR + 0.5, color="gray", ls="--", lw=0.8)
    ax1.axvline(config.EVENING_START_HOUR - 0.5, color="gray", ls="--", lw=0.8)
    ax1.axvline(config.EVENING_END_HOUR + 0.5, color="gray", ls="--", lw=0.8)
    ax1.set_title("Average consumption by hour of day")
    ax1.set_xlabel("Hour of day")
    ax1.set_ylabel("Mean consumption (MW)")
    ax1.set_xticks(range(24))
    ax1.grid(axis="y", alpha=0.3)

    tail = series.iloc[-14 * 24 :]
    ax2.plot(tail.index, tail.values, label="Actual (last 14 days)", color="#1f77b4", linewidth=1.4)
    ax2.plot(forecast.index, forecast.values, label="Iterated forecast", color="#d62728", linewidth=1.4)
    ax2.set_title(f"Iterated consumption forecast — next {config.PEAK_FORECAST_DAYS} days")
    ax2.set_ylabel("Consumption (MW)")
    ax2.legend(loc="best")
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(dest, dpi=130)
    plt.close(fig)
    log.info("Peak plot written to %s", dest)


def main() -> int:
    try:
        build_report()
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())