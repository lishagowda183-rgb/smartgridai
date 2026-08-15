"""Phase 4: weather-aware forecast visualizations.

Generates four PNG artifacts in ml/data/processed/:

  * plot_temperature_vs_consumption.png  - scatter of temperature vs load
  * plot_humidity_vs_consumption.png     - scatter of humidity vs load
  * plot_weather_vs_consumption.png      - mean load by weather condition + a
                                           precipitation presence comparison
  * plot_weather_forecast.png            - actual vs consumption-only vs
                                           weather-aware prediction (last 14
                                           days of the test split)

Run after `python ml/scripts/train_weather_models.py`.
"""

from __future__ import annotations

import logging
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

import config  # noqa: E402
import forecasting  # noqa: E402
from weather_features import code_to_condition  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("plot_weather")


def load_weather_features() -> pd.DataFrame:
    if not config.WEATHER_FEATURES_DATA.exists():
        raise FileNotFoundError(
            f"{config.WEATHER_FEATURES_DATA} missing. Run "
            "`python ml/scripts/weather_features.py` first."
        )
    df = pd.read_parquet(config.WEATHER_FEATURES_DATA)
    df.index = pd.to_datetime(df.index)
    return df


def plot_temperature_vs_consumption(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    sc = ax.scatter(df["temperature"], df[config.CLEANED_COLUMN],
                    s=6, alpha=0.15, c=df["hour"], cmap="viridis")
    ax.set_xlabel("Temperature (°C)")
    ax.set_ylabel("Electricity consumption (MW)")
    ax.set_title("Temperature vs Consumption (colored by hour of day)")
    plt.colorbar(sc, ax=ax, label="hour")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(config.PLOT_TEMP_CONSUMPTION, dpi=130)
    plt.close(fig)
    log.info("Wrote %s", config.PLOT_TEMP_CONSUMPTION)


def plot_humidity_vs_consumption(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.scatter(df["humidity"], df[config.CLEANED_COLUMN], s=6, alpha=0.15, color="#2ca02c")
    ax.set_xlabel("Relative humidity (%)")
    ax.set_ylabel("Electricity consumption (MW)")
    ax.set_title("Humidity vs Consumption")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(config.PLOT_HUMIDITY_CONSUMPTION, dpi=130)
    plt.close(fig)
    log.info("Wrote %s", config.PLOT_HUMIDITY_CONSUMPTION)


def plot_weather_vs_consumption(df: pd.DataFrame) -> None:
    names = {v: k for k, v in config.WEATHER_CONDITIONS.items()}
    df = df.copy()
    df["condition_name"] = df["condition"].map(names)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
    means = df.groupby("condition_name")[config.CLEANED_COLUMN].mean().reindex(
        [names[i] for i in sorted(names)]
    )
    ax1.bar(means.index, means.values, color="#ff7f0e")
    ax1.set_ylabel("Mean consumption (MW)")
    ax1.set_title("Mean Consumption by Weather Condition")
    ax1.tick_params(axis="x", rotation=30)

    rainy = df["precipitation"] > 0.1
    ax2.bar(["dry", "rain > 0.1mm"],
            [df.loc[~rainy, config.CLEANED_COLUMN].mean(), df.loc[rainy, config.CLEANED_COLUMN].mean()],
            color=["#1f77b4", "#7f7f7f"])
    ax2.set_ylabel("Mean consumption (MW)")
    ax2.set_title("Rainy vs Dry Hours")
    for ax in (ax1, ax2):
        ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(config.PLOT_WEATHER_CONSUMPTION, dpi=130)
    plt.close(fig)
    log.info("Wrote %s", config.PLOT_WEATHER_CONSUMPTION)


def plot_weather_forecast(days: int = config.FORECAST_PLOT_DAYS) -> None:
    preds = pd.read_csv(config.PREDICTIONS_WEATHER_CSV, parse_dates=["timestamp"])
    tail = preds[preds["split"] == config.SPLIT_TEST].iloc[-days * 24 :]

    fig, ax = plt.subplots(figsize=(14, 5.5))
    ax.plot(tail["timestamp"], tail["actual"], label="Actual", color="#1f77b4", linewidth=1.6)
    ax.plot(tail["timestamp"], tail["consumption_only"], label="Consumption-only", color="#7f7f7f", linewidth=1.1)
    ax.plot(tail["timestamp"], tail["weather_aware"], label="Weather-aware", color="#d62728", linewidth=1.4)
    ax.set_title(f"Actual vs Predictions — last {days} days of test set")
    ax.set_xlabel("Time")
    ax.set_ylabel("Electricity consumption (MW)")
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(config.PLOT_WEATHER_FORECAST, dpi=130)
    plt.close(fig)
    log.info("Wrote %s", config.PLOT_WEATHER_FORECAST)


def main() -> int:
    try:
        df = load_weather_features()
        plot_temperature_vs_consumption(df)
        plot_humidity_vs_consumption(df)
        plot_weather_vs_consumption(df)
        if not config.PREDICTIONS_WEATHER_CSV.exists():
            raise FileNotFoundError(
                f"{config.PREDICTIONS_WEATHER_CSV} missing. Run "
                "`python ml/scripts/train_weather_models.py` first."
            )
        plot_weather_forecast()
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())