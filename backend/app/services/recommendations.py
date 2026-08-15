"""Deterministic recommendations engine (Phase 11).

Recommendations are produced ONLY when their triggering condition is actually
met by the forecast computation. Every recommendation carries:
  * ``id``            stable identifier
  * ``message``       human-readable guidance
  * ``basis``         the computed fact that triggered it (traceable, never unsupported)

Conditions are derived from the forecast summary, the L/M/H classification and
the peak analysis, so recommendations are always grounded in calculated results.
"""

from __future__ import annotations

import numpy as np


def _share(counts: dict[str, int]) -> float:
    total = max(1, sum(counts.values()))
    return counts.get("HIGH", 0) / total


def _festival_effect_threshold() -> float:
    """Classification band for festival effects (shared with the analysis)."""
    from .. import config as api_config

    return float(api_config.FESTIVAL_EFFECT_THRESHOLD_PCT)


def generate_recommendations(
    counts: dict[str, int],
    change_percent: float,
    peak_to_average_ratio: float,
    evening_share: float | None,
    forecast_type: str,
    projected_annual_growth_pct: float | None = None,
    festival_upcoming: list[dict] | None = None,
) -> list[dict]:
    """Build recommendations from computed forecast metrics.

    Arguments (all computed upstream from real forecast results):
      counts              -> LOW/MEDIUM/HIGH period counts (classification)
      change_percent      -> % change of forecast avg vs historical baseline
      peak_to_average_ratio
      evening_share       -> fraction of forecast demand in evening hours (None if sub-daily)
      forecast_type       -> short_term / medium_term / long_term
      projected_annual_growth_pct -> annualized long-term growth (long_term only)
      festival_upcoming   -> upcoming festival entries (Phase 13); each carries the
                             historically observed effect when data is sufficient.
    """
    recommendations: list[dict] = []
    high_share = _share(counts)
    low_share = counts.get("LOW", 0) / max(1, sum(counts.values()))

    if high_share >= 0.5:
        recommendations.append(
            {
                "id": "high_demand",
                "message": (
                    "High electricity demand is expected during this period "
                    f"({high_share * 100:.0f}% of the forecast classified HIGH). "
                    "Consider shifting flexible loads away from the predicted peak period."
                ),
                "basis": f"High-classified periods account for {high_share * 100:.0f}% of the forecast.",
            }
        )

    if low_share >= 0.5:
        recommendations.append(
            {
                "id": "low_demand",
                "message": "Demand is expected to remain relatively low during this period.",
                "basis": f"Low-classified periods account for {low_share * 100:.0f}% of the forecast.",
            }
        )

    if change_percent >= 5.0 and forecast_type in ("short_term", "medium_term"):
        recommendations.append(
            {
                "id": "rising_trend",
                "message": (
                    "Consumption is trending upward compared with the historical "
                    "baseline. Consider reviewing high-consumption appliances/processes."
                ),
                "basis": f"Forecast average is +{change_percent:.1f}% vs the historical baseline.",
            }
        )
    elif change_percent <= -5.0 and forecast_type in ("short_term", "medium_term"):
        recommendations.append(
            {
                "id": "falling_trend",
                "message": (
                    "Consumption is trending downward compared with the historical "
                    "baseline — a good time to lock in a stable baseline."
                ),
                "basis": f"Forecast average is {change_percent:.1f}% vs the historical baseline.",
            }
        )

    if evening_share is not None and evening_share >= 0.35 and peak_to_average_ratio >= 1.2:
        recommendations.append(
            {
                "id": "peak_concentration",
                "message": (
                    "Consumption is concentrated during evening hours. Consider "
                    "shifting flexible usage to lower-demand periods."
                ),
                "basis": (
                    f"{evening_share * 100:.0f}% of forecast demand falls in the "
                    "evening window (17–22)."
                ),
            }
        )

    if forecast_type == "long_term" and projected_annual_growth_pct is not None:
        if projected_annual_growth_pct >= 3.0:
            recommendations.append(
                {
                    "id": "high_long_term_growth",
                    "message": (
                        "Long-term consumption is projected to increase. Consider "
                        "energy-efficiency improvements and capacity planning."
                    ),
                    "basis": f"Projected ~{projected_annual_growth_pct:.1f}% annual growth from the historical trend.",
                }
            )
        elif projected_annual_growth_pct <= -3.0:
            recommendations.append(
                {
                    "id": "long_term_decline",
                    "message": (
                        "Long-term consumption is projected to decline — capacity "
                        "planning may be able to reflect a smaller future baseline."
                    ),
                    "basis": f"Projected ~{abs(projected_annual_growth_pct):.1f}% annual decline from the historical trend.",
                }
            )

    # Phase 13 — festival recommendations, grounded ONLY in observed data. Each
    # message cites the household's own historical effect (never causality).
    if festival_upcoming:
        for fest in festival_upcoming:
            pct = fest.get("historical_effect_percent")
            name = fest.get("festival_name")
            if pct is None:
                recommendations.append(
                    {
                        "id": "festival_insufficient_data",
                        "message": (
                            f"There is not enough historical household data to "
                            f"estimate a festival-specific effect during "
                            f"{name} on {fest.get('date')}."
                        ),
                        "basis": "Fraction of festival windows below the minimum historical observations.",
                    }
                )
                continue
            if pct >= _festival_effect_threshold():
                recommendations.append(
                    {
                        "id": "festival_higher",
                        "message": (
                            f"Your household historically consumed about "
                            f"{abs(pct):.1f}% more electricity around {name}. "
                            f"Consider planning high-load appliance usage efficiently "
                            f"during this period."
                        ),
                        "basis": (
                            f"Observed {pct:+.1f}% around {name} vs the household's "
                            "comparable non-festival baseline."
                        ),
                    }
                )
            elif pct <= -_festival_effect_threshold():
                recommendations.append(
                    {
                        "id": "festival_lower",
                        "message": (
                            f"Your household historically consumed about "
                            f"{abs(pct):.1f}% less electricity around this festival "
                            f"period ({name})."
                        ),
                        "basis": (
                            f"Observed {pct:+.1f}% around {name} vs the household's "
                            "comparable non-festival baseline."
                        ),
                    }
                )
            else:
                recommendations.append(
                    {
                        "id": "festival_similar",
                        "message": (
                            f"Your household's historical electricity consumption "
                            f"during this festival ({name}) is similar to your "
                            f"normal usage."
                        ),
                        "basis": (
                            f"Observed {pct:+.1f}% around {name} vs the household's "
                            "comparable non-festival baseline — inside the similar band."
                        ),
                    }
                )

    if not recommendations:
        recommendations.append(
            {
                "id": "stable_demand",
                "message": (
                    "Demand is expected to remain fairly stable compared with the "
                    "historical baseline. No urgent action is suggested."
                ),
                "basis": "Change vs baseline and classification shares are within normal bounds.",
            }
        )
    return recommendations


def evening_demand_share(values, timestamps, evening_start: int = 17, evening_end: int = 22) -> float | None:
    """Share of total forecast demand occurring in the evening window [17, 22).

    Returns None when the forecasting frequency is coarser than hourly (no
    reliable hour-of-day information).
    """
    import pandas as pd

    if values is None or timestamps is None or len(values) != len(timestamps):
        return None
    ts = pd.to_datetime(list(timestamps))
    hours = ts.hour.values
    total = float(np.asarray(values, dtype=float).sum())
    if total <= 0:
        return 0.0
    evening = float(np.asarray(values, dtype=float)[(hours >= evening_start) & (hours < evening_end)].sum())
    return round(evening / total, 4)