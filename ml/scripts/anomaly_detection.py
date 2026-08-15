"""Phase 5: anomaly detection for the hourly electricity-consumption series.

Flags consumption anomalies with four complementary detectors:

  * rolling_zscore      -> deviation from a trailing 7-day rolling mean/std
                           (catches sudden spikes and abrupt drops)
  * hourly_profile      -> deviation from the historical distribution of the
                           same hour of day (consumption significantly
                           different from its usual pattern)
  * nighttime           -> night hours (config.NIGHT_START..NIGHT_END) flagged
                           against their own night-only distribution
                           (abnormal nighttime usage)
  * isolation_forest    -> Isolation Forest on the Phase 2 lag + rolling
                           consumption features (model-based/unsupervised)

Every detected point is reported as a row with: timestamp, value, method,
type, score (z-score or isolation score) and a severity bucket
(moderate / high / critical) derived from the magnitude of the deviation.

Pure functions are unit-testable on small synthetic inputs; ``main()``
persists:

  * ml/data/processed/anomaly_report.json -> the full report
  * ml/data/processed/anomalies_plot.png  -> series with flagged points,
                                             colored by severity
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

import matplotlib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import config  # noqa: E402
import forecasting  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("anomaly_detection")

SEVERITY_MODERATE = "moderate"
SEVERITY_HIGH = "high"
SEVERITY_CRITICAL = "critical"


def rolling_zscore(
    series: pd.Series, window: int = config.ANOMALY_ROLLING_WINDOW
) -> pd.Series:
    """Z-score of each value against the trailing `window` hours (exclusive).

    The current value is excluded from its own window so a spike cannot
    dilute the baseline it is measured against.
    """
    roll_mean = series.shift(1).rolling(window).mean()
    roll_std = series.shift(1).rolling(window).std()
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (series - roll_mean) / roll_std
    z[(roll_std == 0) | roll_std.isna()] = np.nan
    return z


def rolling_anomalies(
    series: pd.Series,
    window: int = config.ANOMALY_ROLLING_WINDOW,
    cutoff: float = config.ANOMALY_ZSCORE_CUTOFF,
) -> pd.DataFrame:
    """Anomalies from the rolling z-score: positive = spike, negative = drop."""
    z = rolling_zscore(series, window=window)
    mask = z.abs() >= cutoff
    rows = []
    for ts in series.index[mask]:
        value = float(series.loc[ts])
        zval = float(z.loc[ts])
        rows.append(
            {
                "timestamp": str(ts),
                "value": round(value, 2),
                "method": "rolling_zscore",
                "type": "spike" if zval > 0 else "drop",
                "score": round(zval, 2),
            }
        )
    return pd.DataFrame(rows)


def hourly_profile_zscore(series: pd.Series) -> pd.Series:
    """Z-score of each value against the historical distribution of its hour."""
    grouped = pd.DataFrame({"hour": series.index.hour, "value": series.values}).groupby("hour")["value"]
    mean = grouped.transform("mean")
    std = grouped.transform("std")
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (series.values - mean.values) / std.values
    z[(std.values == 0) | np.isnan(std.values)] = np.nan
    return pd.Series(z, index=series.index)


def hourly_profile_anomalies(
    series: pd.Series, cutoff: float = config.ANOMALY_ZSCORE_CUTOFF
) -> pd.DataFrame:
    """Anomalies deviating from the usual same-hour consumption distribution."""
    z = hourly_profile_zscore(series)
    mask = z.abs() >= cutoff
    rows = []
    for ts in series.index[mask]:
        value = float(series.loc[ts])
        zval = float(z.loc[ts])
        rows.append(
            {
                "timestamp": str(ts),
                "value": round(value, 2),
                "method": "hourly_profile",
                "type": "high" if zval > 0 else "low",
                "score": round(zval, 2),
            }
        )
    return pd.DataFrame(rows)


def nighttime_anomalies(
    series: pd.Series,
    start_hour: int = config.NIGHT_START_HOUR,
    end_hour: int = config.NIGHT_END_HOUR,
    cutoff: float = config.ANOMALY_NIGHT_ZSCORE_CUTOFF,
) -> pd.DataFrame:
    """Night hours whose usage deviates from the night-only distribution."""
    night = series[(series.index.hour >= start_hour) & (series.index.hour <= end_hour)]
    mean, std = float(night.mean()), float(night.std())
    if std == 0 or np.isnan(std):
        return pd.DataFrame(columns=["timestamp", "value", "method", "type", "score"])
    z = (night - mean) / std
    mask = z.abs() >= cutoff
    rows = []
    for ts in night.index[mask]:
        value = float(night.loc[ts])
        zval = float(z.loc[ts])
        rows.append(
            {
                "timestamp": str(ts),
                "value": round(value, 2),
                "method": "nighttime",
                "type": "abnormal_night_high" if zval > 0 else "abnormal_night_low",
                "score": round(zval, 2),
            }
        )
    return pd.DataFrame(rows)


def isolation_forest_anomalies(
    series: pd.Series,
    contamination: float = config.ANOMALY_IF_CONTAMINATION,
    n_estimators: int = config.ANOMALY_IF_N_ESTIMATORS,
    random_state: int = config.ANOMALY_IF_RANDOM_STATE,
) -> pd.DataFrame:
    """Isolation Forest over the Phase 2 lag + rolling feature columns."""
    df = forecasting.load_features()
    if not df.index.equals(series.index):
        df = df.reindex(series.index)
    cols = [c for c in forecasting.feature_columns(df) if c not in ("split",)]
    X = df[cols].to_numpy()
    isof = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        random_state=random_state,
        n_jobs=config.RF_N_JOBS,
    )
    preds = isof.fit_predict(X)
    scores = -isof.score_samples(X)
    mask = preds == -1
    rows = []
    for ts in series.index[mask]:
        k = series.index.get_loc(ts)
        rows.append(
            {
                "timestamp": str(ts),
                "value": round(float(series.iloc[k]), 2),
                "method": "isolation_forest",
                "type": "outlier",
                "score": round(float(scores[k]), 2),
            }
        )
    return pd.DataFrame(rows)


def severity_of(score: float) -> str:
    """Map a z-score magnitude to a severity bucket."""
    score = abs(score)
    if score >= 5.0:
        return SEVERITY_CRITICAL
    if score >= 4.0:
        return SEVERITY_HIGH
    return SEVERITY_MODERATE


def combine_anomalies(
    series: pd.Series, dataframes: list[pd.DataFrame]
) -> pd.DataFrame:
    """Concatenate all detectors, assign severity, sort by timestamp."""
    frames = [df for df in dataframes if df is not None and not df.empty]
    if not frames:
        return pd.DataFrame(
            columns=["timestamp", "value", "method", "type", "score", "severity"]
        )
    combined = pd.concat(frames, ignore_index=True)
    combined["severity"] = combined["score"].map(severity_of)
    combined = combined.sort_values("timestamp").reset_index(drop=True)
    return combined


def build_report() -> dict:
    """Run every detector on the full series, persist report + plot."""
    config.ensure_dirs()
    df = forecasting.load_features()
    series = df[config.CLEANED_COLUMN]

    roll = rolling_anomalies(series)
    prof = hourly_profile_anomalies(series)
    night = nighttime_anomalies(series)
    iso = isolation_forest_anomalies(series)
    combined = combine_anomalies(series, [roll, prof, night, iso])

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "series": {
            "rows": int(len(series)),
            "start": str(series.index.min()),
            "end": str(series.index.max()),
        },
        "configuration": {
            "rolling_window": config.ANOMALY_ROLLING_WINDOW,
            "zscore_cutoff": config.ANOMALY_ZSCORE_CUTOFF,
            "night_window": f"{config.NIGHT_START_HOUR}-{config.NIGHT_END_HOUR}",
            "night_zscore_cutoff": config.ANOMALY_NIGHT_ZSCORE_CUTOFF,
            "isolation_forest": {
                "contamination": config.ANOMALY_IF_CONTAMINATION,
                "n_estimators": config.ANOMALY_IF_N_ESTIMATORS,
                "random_state": config.ANOMALY_IF_RANDOM_STATE,
            },
        },
        "counts_by_method": combined["method"].value_counts().to_dict(),
        "counts_by_type": combined["type"].value_counts().to_dict(),
        "counts_by_severity": combined["severity"].value_counts().to_dict(),
        "anomalies": combined.to_dict(orient="records"),
    }
    config.ANOMALY_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("Anomaly report written to %s", config.ANOMALY_REPORT)
    build_plot(series, combined, config.ANOMALY_PLOT)
    return report


def build_plot(series: pd.Series, anomalies: pd.DataFrame, dest) -> None:
    """Plot the series with anomaly points colored by severity bucket."""
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(series.index, series.values, color="#1f77b4", linewidth=0.6, label="Consumption")
    severity_colors = {
        SEVERITY_MODERATE: "#ffbb33",
        SEVERITY_HIGH: "#ff8c00",
        SEVERITY_CRITICAL: "#d62728",
    }
    if not anomalies.empty:
        dt = pd.to_datetime(anomalies["timestamp"])
        for sev, color in severity_colors.items():
            sub = anomalies[anomalies["severity"] == sev]
            if not sub.empty:
                ax.scatter(
                    pd.to_datetime(sub["timestamp"]).values,
                    sub["value"].values,
                    s=22,
                    color=color,
                    label=f"anomaly ({sev})",
                    zorder=3,
                )
        ax.set_xlim(series.index.min(), series.index.max())
    ax.set_title("Consumption anomalies by severity")
    ax.set_xlabel("Time")
    ax.set_ylabel("Electricity consumption (MW)")
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(dest, dpi=130)
    plt.close(fig)
    log.info("Anomaly plot written to %s", dest)


def main() -> int:
    try:
        build_report()
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())