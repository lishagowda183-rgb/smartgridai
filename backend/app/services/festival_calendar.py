"""Deterministic Indian festival / holiday calendar + household analysis (Phase 13).

Two clearly separated responsibilities:

1. A *calendar*: which dates carry a festival/holiday, plus per-timestamp features
   (``festival_features``). This is configuration, not a model — the built-in
   table below is a curated pan-Indian approximation (the lunisolar/Eid dates
   drift by region and by lunar sighting) and is fully overridable through
   ``FESTIVAL_CALENDAR_JSON``. Dates are NOT derived from any LLM.
2. An *observed household analysis*: for the uploaded history only, compute the
   household's own festival-window average versus a comparable non-festival
   baseline. The resulting effect (HIGHER / LOWER / SIMILAR) is learned from the
   data, never assumed. Insufficient observations disable the effect entirely.

Honesty rules enforced here (and documented in the report):
  * a lack of festival history NEVER breaks forecasting;
  * festival effects are never forced to be positive;
  * language is "historically observed in your data", never causality.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .. import config as api_config  # noqa: E402 (bootstraps ml/scripts sys.path)

# Message used whenever there is not enough historical data. Kept identical in
# the response and the recommendations so the UI can rely on one phrase.
INSUFFICIENT_MESSAGE = (
    "Insufficient historical household data to estimate a festival-specific effect."
)

# Festival classifications (labels are stable identifiers used by the UI).
EFFECT_HIGHER = "HIGHER_THAN_NORMAL"
EFFECT_LOWER = "LOWER_THAN_NORMAL"
EFFECT_SIMILAR = "SIMILAR_TO_NORMAL"

# National holidays keyed by month -> day (fixed calendar dates).
NATIONAL_HOLIDAYS: dict[int, int] = {
    1: 26,   # Republic Day
    8: 15,   # Independence Day
    10: 2,   # Gandhi Jayanti
    12: 25,  # Christmas
}

# Curated pan-Indian festival dates, keyed by year. Every value is a (month, day)
# tuple for that year's observed festival day. These are approximate to the
# regional lunisolar calendars (documented; override via FESTIVAL_CALENDAR_JSON).
BUILTIN_CALENDAR: dict[str, dict[int, tuple[int, int]]] = {
    "Diwali": {2023: (11, 12), 2024: (11, 1), 2025: (10, 20), 2026: (11, 8), 2027: (10, 29), 2028: (10, 17)},
    "Holi": {2023: (3, 8), 2024: (3, 25), 2025: (3, 14), 2026: (3, 4), 2027: (3, 22), 2028: (3, 11)},
    "Dussehra": {2023: (10, 24), 2024: (10, 12), 2025: (10, 2), 2026: (10, 21), 2027: (10, 10), 2028: (9, 28)},
    "Ganesh Chaturthi": {2023: (9, 19), 2024: (9, 7), 2025: (8, 27), 2026: (9, 15), 2027: (9, 5), 2028: (8, 24)},
    "Ugadi": {2023: (3, 22), 2024: (4, 9), 2025: (3, 30), 2026: (3, 19), 2027: (4, 7), 2028: (3, 26)},
    "Eid al-Fitr": {2023: (4, 21), 2024: (4, 10), 2025: (3, 30), 2026: (3, 20), 2027: (3, 10), 2028: (2, 27)},
    "Eid al-Adha": {2023: (6, 28), 2024: (6, 16), 2025: (6, 6), 2026: (5, 26), 2027: (5, 16), 2028: (5, 5)},
    "Onam": {2023: (8, 29), 2024: (9, 15), 2025: (8, 30), 2026: (9, 19), 2027: (9, 9), 2028: (8, 29)},
    "Pongal / Makar Sankranti": {2023: (1, 15), 2024: (1, 15), 2025: (1, 14), 2026: (1, 14), 2027: (1, 14), 2028: (1, 15)},
    "Raksha Bandhan": {2023: (8, 30), 2024: (8, 19), 2025: (8, 9), 2026: (8, 28), 2027: (8, 17), 2028: (8, 5)},
    "Janmashtami": {2023: (9, 7), 2024: (8, 26), 2025: (8, 16), 2026: (9, 4), 2027: (8, 24), 2028: (8, 13)},
    "Navratri": {2023: (10, 15), 2024: (10, 3), 2025: (9, 22), 2026: (10, 11), 2027: (10, 1), 2028: (9, 20)},
}

CALENDAR_ATTR = (
    "Festival dates are a curated pan-Indian approximation (lunisolar/Eid dates "
    "vary regionally and by lunar sighting). Customize via FESTIVAL_CALENDAR_JSON "
    "for state/region-specific accuracy."
)


def _load_calendar() -> dict[str, dict[int, tuple[int, int]]]:
    """Applied calendar: the built-in table merged with any user JSON override.

    An override file (a JSON object mapping festival name -> {year: [m, d]})
    replaces that festival's entries entirely, so region-specific dates can be
    supplied without touching code.
    """
    calendar = {name: dict(v) for name, v in BUILTIN_CALENDAR.items()}
    path = api_config.FESTIVAL_CALENDAR_JSON
    if not path or not Path(path).is_file():
        return calendar
    try:
        with Path(path).open("r", encoding="utf-8") as fh:
            overrides = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return calendar
    for name, by_year in overrides.items():
        if not isinstance(by_year, dict):
            continue
        entries = {}
        for year, md in by_year.items():
            try:
                entries[int(year)] = (int(md[0]), int(md[1]))
            except (TypeError, ValueError, IndexError):
                continue
        if entries:
            calendar[name] = entries
    return calendar


# ---------------------------------------------------------------------------
# Festival occurrences (calendar layer)
# ---------------------------------------------------------------------------
def festival_occurrences(
    start: pd.Timestamp, end: pd.Timestamp, festival: str | None = None
) -> list[dict]:
    """Festival occurrences with dates in [start, end) (naive, inclusive days).

    ``festival`` optionally filters to a single name. Returns a deterministic
    list of ``{"name": str, "date": pd.Timestamp, "national_holiday": bool}``.
    """
    start = pd.Timestamp(start).normalize()
    end = pd.Timestamp(end).normalize()
    calendar = _load_calendar()
    occurrences: list[dict] = []
    years = range(start.year - 1, end.year + 2)
    for name, by_year in calendar.items():
        if festival is not None and name != festival:
            continue
        for year in years:
            md = by_year.get(year)
            if md is None:
                continue
            date = pd.Timestamp(year, md[0], md[1]).normalize()
            if start <= date < end:
                occurrences.append(
                    {"name": name, "date": date, "national_holiday": False}
                )
    for month, day in NATIONAL_HOLIDAYS.items():
        if festival is not None and _holiday_name(month) != festival:
            continue
        for _year in range(start.year, end.year):
            date = pd.Timestamp(_year, month, day)
            if start <= date < end:
                occurrences.append(
                    {"name": _holiday_name(month),
                     "date": date, "national_holiday": True}
                )
    occurrences.sort(key=lambda o: (o["date"], o["name"]))
    return occurrences


def _holiday_name(month: int) -> str:
    return {
        1: "Republic Day",
        8: "Independence Day",
        10: "Gandhi Jayanti",
        12: "Christmas",
    }.get(month, "National Holiday")


def window_limits(date: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Festival window: ``date - before`` .. ``date + after`` (inclusive days)."""
    before = int(api_config.FESTIVAL_WINDOW_BEFORE)
    after = int(api_config.FESTIVAL_WINDOW_AFTER)
    return date - pd.Timedelta(days=before), date + pd.Timedelta(days=after)


def _nearest_occurrence(
    day: pd.Timestamp, occurrences: list[dict], before: int, after: int
) -> dict | None:
    """The festival whose window contains ``day`` (nearest start wins ties)."""
    best = None
    best_delta = None
    for occ in occurrences:
        delta = (day - occ["date"]).days
        if -before <= delta <= after:
            score = abs(delta)
            if best_delta is None or score < best_delta:
                best, best_delta = occ, score
    return best


def festival_features(index) -> pd.DataFrame:
    """Per-timestamp festival/calendar feature rows (weekly has its own method).

    Columns (mirroring the Phase 13 spec, no duplicates with the existing
    ``feature_engineering`` timestamp features beyond ``is_weekend`` which is
    intentionally shared with ``hour``/``day_of_week``):

      is_festival        : 1 when inside any festival window
      festival_name      : nearest festival inside the window ("" otherwise)
      is_holiday         : 1 for a national holiday or a festival day
      is_weekend         : 1 for Sat/Sun
      days_before_festival : days until the festival (within the window, else 0)
      days_after_festival  : days since the festival (within the window, else 0)
      festival_day       : 1 on the festival date itself
      festival_window    : 1 inside any festival window
    """
    idx = pd.DatetimeIndex(pd.to_datetime(index))
    if len(idx) == 0:
        return pd.DataFrame(
            columns=["is_festival", "festival_name", "is_holiday", "is_weekend",
                     "days_before_festival", "days_after_festival",
                     "festival_day", "festival_window"],
            index=idx,
        )
    before = int(api_config.FESTIVAL_WINDOW_BEFORE)
    after = int(api_config.FESTIVAL_WINDOW_AFTER)
    occurrences = festival_occurrences(idx.min(), idx.max())
    holiday_dates = {
        occ["date"] for occ in occurrences if occ["national_holiday"]
    }

    rows = []
    for ts in idx:
        day = ts.normalize()
        occ = _nearest_occurrence(day, occurrences, before, after)
        is_window = occ is not None
        delta = (day - occ["date"]).days if occ is not None else 0
        is_festival_day = is_window and delta == 0
        days_before = max(0, -delta) if is_window and delta < 0 else 0
        days_after = delta if is_window and delta > 0 else 0
        rows.append({
            "is_festival": int(is_window),
            "festival_name": occ["name"] if is_window else "",
            "is_holiday": int(
                is_festival_day or day in holiday_dates
            ),
            "is_weekend": int(day.dayofweek >= 5),
            "days_before_festival": int(days_before),
            "days_after_festival": int(days_after),
            "festival_day": int(is_festival_day),
            "festival_window": int(is_window),
        })
    return pd.DataFrame(rows, index=idx)


# ---------------------------------------------------------------------------
# Historical household analysis (observation layer — the data, not the model)
# ---------------------------------------------------------------------------
def _min_observations() -> int:
    return int(api_config.FESTIVAL_MIN_OBSERVATIONS)


def _effect_threshold() -> float:
    return float(api_config.FESTIVAL_EFFECT_THRESHOLD_PCT)


def analyze_historical_festivals(series: pd.Series) -> list[dict]:
    """Festival-by-festival analysis learned solely from the uploaded history.

    For every festival with enough *in-window* observations it computes a
    comparable non-festival baseline (same weekday, same season ±30 days,
    excluding festival windows — sub-daily data also matches the hour-of-day)
    and then the difference. Classification uses
    ``FESTIVAL_EFFECT_THRESHOLD_PCT`` (±). Festivals below the observation
    minimum return ``data_available: False`` with no fabricated numbers.
    """
    if series is None or len(series) == 0:
        return []
    idx = pd.DatetimeIndex(series.index)
    freq = _frequency_hint(series, idx)
    before = int(api_config.FESTIVAL_WINDOW_BEFORE)
    after = int(api_config.FESTIVAL_WINDOW_AFTER)

    occurrences = festival_occurrences(idx.min(), idx.max())
    results: dict[str, dict] = {}
    for name in sorted({o["name"] for o in occurrences}):
        results[name] = _analyze_one(series, freq, occurrences, name, before, after)
    return [results[k] for k in sorted(results) if results[k] is not None]


def _frequency_hint(series: pd.Series, idx: pd.DatetimeIndex) -> str:
    deltas = idx.to_series().diff().dropna()
    if len(deltas) == 0:
        return "daily"
    seconds = float(deltas.mode().iloc[0].total_seconds())
    if seconds <= 3600:
        return "subdaily"
    if seconds == 86400:
        return "daily"
    return "coarse"


def _analyze_one(
    series: pd.Series,
    freq: str,
    occurrences: list[dict],
    name: str,
    before: int,
    after: int,
) -> dict | None:
    """Compute the observed effect for a single festival (or None if absent)."""
    own = [o for o in occurrences if o["name"] == name and not o["national_holiday"]]
    if not own:
        # National holiday handled through the same path (name matches an entry).
        own = [o for o in occurrences if o["name"] == name]
    if not own:
        return None

    window_mask = np.zeros(len(series), dtype=bool)
    window_dates: list[pd.Timestamp] = []
    for occ in own:
        lo, hi = occ["date"] - pd.Timedelta(days=before), occ["date"] + pd.Timedelta(days=after)
        window_mask |= (series.index >= lo) & (series.index <= hi)
        window_dates.append(occ["date"])

    festival_values = series[window_mask].dropna()
    observation_count = int(len(festival_values))
    if observation_count < _min_observations():
        return {
            "festival_name": name,
            "date": str(own[0]["date"].date()),
            "data_available": False,
            "observation_count": observation_count,
            "minimum_observations": _min_observations(),
            "note": INSUFFICIENT_MESSAGE,
        }

    baseline = _comparable_baseline(series, window_mask, window_dates, own, before, after, freq)
    normal_avg = float(baseline) if baseline and baseline > 0 else float(series[~window_mask].mean())
    festival_avg = float(festival_values.mean())
    diff_kwh = festival_avg - normal_avg
    diff_pct = (diff_kwh / normal_avg * 100.0) if normal_avg else 0.0

    return {
        "festival_name": name,
        "date": str(own[0]["date"].date()),
        "data_available": True,
        "normal_average_kwh": round(normal_avg, 4),
        "festival_average_kwh": round(festival_avg, 4),
        "difference_kwh": round(diff_kwh, 4),
        "difference_percent": round(diff_pct, 2),
        "observation_count": observation_count,
        "classification": classify_effect(diff_pct),
        "baseline_method": (
            "same weekday (+ hour of day for sub-daily data) over the same "
            "season (±30 days), excluding festival windows"
        ),
    }


def _comparable_baseline(
    series: pd.Series,
    window_mask: np.ndarray,
    window_dates: list[pd.Timestamp],
    own: list[dict],
    before: int,
    after: int,
    freq: str,
) -> float:
    """Non-festival baseline: same weekday/season as *each* festival window.

    For each festival occurrence, candidate points must lie within ±30 days of
    that occurrence, share its weekday (and hour for sub-daily data), and not be
    inside ANY festival window. The mean across occurrences is the baseline.
    """
    idx = series.index
    values = series.values.astype(float)
    candidates = ~window_mask
    occurrences = festival_occurrences(idx.min(), idx.max())

    def _in_any_window(ts: pd.Timestamp) -> bool:
        for occ in occurrences:
            lo, hi = occ["date"] - pd.Timedelta(days=before), occ["date"] + pd.Timedelta(days=after)
            if lo <= ts <= hi:
                return True
        return False

    totals: list[float] = []
    for occ_date in window_dates:
        lo = occ_date - pd.Timedelta(days=30)
        hi = occ_date + pd.Timedelta(days=30)
        mask = (idx >= lo) & (idx <= hi) & candidates.copy()
        if freq == "subdaily":
            mask &= (idx.hour == occ_date.hour)
        mask &= (idx.dayofweek == occ_date.dayofweek)
        # Exclude other-festival windows too, not just this festival's.
        for i, ts in enumerate(idx):
            if mask[i] and _in_any_window(ts):
                mask[i] = False
        chunk = values[mask]
        if len(chunk):
            totals.append(float(np.mean(chunk)))
    return float(np.mean(totals)) if totals else 0.0


def classify_effect(diff_percent: float) -> str:
    """HIGHER / LOWER / SIMILAR vs the household's own baseline (config threshold)."""
    thresh = _effect_threshold()
    if diff_percent >= thresh:
        return EFFECT_HIGHER
    if diff_percent <= -thresh:
        return EFFECT_LOWER
    return EFFECT_SIMILAR


# ---------------------------------------------------------------------------
# Future festivals + forecast incorporation
# ---------------------------------------------------------------------------
def upcoming_festivals(
    series_end: pd.Timestamp, days: int, analysis: list[dict]
) -> list[dict]:
    """Festivals inside the forecast horizon, joined to any learned observation.

    Each entry is calendar info (always available) plus, when the household has
    enough data, the historically observed effect. Never invents an effect.
    """
    end = pd.Timestamp(series_end).normalize()
    start = end + pd.Timedelta(days=1)
    horizon_end = start + pd.Timedelta(days=days)
    occs = festival_occurrences(start, horizon_end)
    effects = {a["festival_name"]: a for a in analysis}
    before = int(api_config.FESTIVAL_WINDOW_BEFORE)
    after = int(api_config.FESTIVAL_WINDOW_AFTER)
    upcoming = []
    for occ in occs:
        effect = effects.get(occ["name"])
        entry = {
            "festival_name": occ["name"],
            "date": str(occ["date"].date()),
            "window_start": str((occ["date"] - pd.Timedelta(days=before)).date()),
            "window_end": str((occ["date"] + pd.Timedelta(days=after)).date()),
            "national_holiday": bool(occ["national_holiday"]),
            "festival_data_available": bool(effect and effect.get("data_available")),
        }
        if effect and effect.get("data_available"):
            entry["historical_effect_percent"] = effect.get("difference_percent")
            entry["historical_classification"] = effect.get("classification")
            entry["festival_effect_percent"] = effect.get("difference_percent")
            entry["note"] = "Based on historical household data."
        else:
            entry["historical_effect_percent"] = None
            entry["historical_classification"] = None
            entry["festival_effect_percent"] = None
            entry["note"] = INSUFFICIENT_MESSAGE
        upcoming.append(entry)
    return upcoming


def adjust_forecast(
    forecast: pd.Series, upcoming: list[dict]
) -> tuple[pd.Series, list[dict]]:
    """Scale forecast values inside festival windows by the *observed* ratio.

    Only applied when the household has sufficient data AND the observed effect
    is distinct from normal (outside the SIMILAR band). The multiplier is
    ``festival_average / normal_average`` — it can be above or below 1.0
    depending on the data; it is never forced positive. Returns
    ``(adjusted_forecast, applied)`` where ``applied`` lists the festivals whose
    window was actually scaled.
    """
    if forecast is None or len(forecast) == 0:
        return forecast, []
    thresh = _effect_threshold()
    applied = []
    result = forecast.copy()
    for entry in upcoming:
        if not entry.get("festival_data_available"):
            continue
        pct = entry.get("festival_effect_percent")
        if pct is None:
            continue
        # A SIMILAR-to-normal effect is not applied: only clearly higher/lower
        # observations move the forecast (honesty, no fabricated festival lift).
        if abs(pct) < thresh:
            continue
        multiplier = 1.0 + float(pct) / 100.0
        # Guard the forecast against runaway distortion (documented limitation).
        multiplier = float(np.clip(multiplier, 0.5, 1.5))
        if abs(multiplier - 1.0) < 1e-9:
            continue
        lo = pd.Timestamp(entry["window_start"])
        hi = pd.Timestamp(entry["window_end"])
        mask = (result.index >= lo) & (result.index <= hi)
        if mask.any():
            result.loc[mask] = result.loc[mask] * multiplier
            applied.append({**entry, "applied_multiplier": round(multiplier, 4)})
    return result, applied


def festivals_payload(
    series: pd.Series, days: int, weather_used: bool, forecast_type: str,
    weather_status: str | None = None, weather_source: str | None = None,
    weather_features_used: list[str] | None = None, weather_fetched_at: str | None = None,
) -> dict:
    """Assemble the additive ``festivals`` response block (never breaks others)."""
    analysis = analyze_historical_festivals(series)
    upcoming = upcoming_festivals(series.index.max(), days, analysis)
    note = (
        "Festival/calendar dates for the forecast period are KNOWN from the "
        "deterministic calendar. "
        + CALENDAR_ATTR
    )
    if forecast_type == "long_term":
        note += (
            " Future weather is NOT available at this horizon; the forecast uses "
            "historical consumption, time patterns and festival/calendar features."
        )
    weather_parts: list[str] = []
    if weather_status:
        weather_parts.append(f"status={weather_status}")
        if weather_source:
            weather_parts.append(f"source={weather_source}")
    if weather_features_used:
        weather_parts.append(f"features={','.join(weather_features_used)}")
    weather_note = (
        "Weather is available and combined with festival/calendar features "
        "where they overlap." if weather_used
        else "Weather data unavailable for this forecast period. Forecast uses "
             "historical consumption, time patterns and festival/calendar features."
    )
    if weather_parts:
        weather_note = f"Weather: {'; '.join(weather_parts)}. " + weather_note
    return {
        "analysis": analysis,
        "upcoming": upcoming,
        "calendar_note": CALENDAR_ATTR,
        "note": note,
        "weather_note": weather_note,
    }