"""Phase 7 API configuration.

API-specific settings are read from environment variables (`.env`). Everything
shared with the ML pipeline — paths, units, scopes, model artifact locations —
comes from ``ml/scripts/config`` so the API never redefines them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Make ml/scripts importable first so `import config` below resolves to the
# shared pipeline config (same bootstrap the test suite uses).
_SCRIPTS = Path(__file__).resolve().parents[2] / "ml" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import config as ml_config  # noqa: E402  (ml/scripts/config)

load_dotenv(ml_config.PROJECT_ROOT / ".env")


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, default)
    return default if value is None or not str(value).strip() else value


# --- API server --------------------------------------------------------------
API_HOST = _env("API_HOST", "127.0.0.1")
API_PORT = int(_env("API_PORT", "8000"))
API_PREFIX = _env("API_PREFIX", "/api/v1")
LOG_LEVEL = _env("LOG_LEVEL", "INFO").upper()

# Comma-separated list of allowed CORS origins ("*" allows any origin).
CORS_ORIGINS = [o.strip() for o in _env("CORS_ORIGINS", "*").split(",") if o.strip()]

# --- Endpoint defaults -------------------------------------------------------
API_DEFAULT_TARIFF = _env("API_DEFAULT_TARIFF", "time_of_use")
API_DEFAULT_HORIZON = _env("API_DEFAULT_HORIZON", "1m")

# Allowed hourly-forecast horizons (hours).
ALLOWED_FORECAST_HOURS = [24, 48, 72]
MAX_FORECAST_DAYS = 30
MAX_HISTORY_LIMIT = 10_000
DEFAULT_HISTORY_LIMIT = 1_000
MAX_ANOMALY_LIMIT = 5_000

# --- User upload + flexible forecasting (Phase 11) -----------------------------
# Temporary storage for uploaded consumption files + parsed datasets. Every
# dataset is isolated behind a generated dataset_id and is never mixed with the
# original project series (forecasts run only on the uploaded data).
UPLOAD_DIR = Path(_env("UPLOAD_DIR", str(ml_config.PROJECT_ROOT / "ml" / "data" / "uploads")))

# Maximum accepted upload size (bytes) and file types.
MAX_UPLOAD_SIZE_MB = int(_env("MAX_UPLOAD_SIZE_MB", "25"))
MAX_UPLOAD_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = [
    e.strip().lower()
    for e in _env("ALLOWED_UPLOAD_EXTENSIONS", ".csv,.xlsx").split(",")
    if e.strip()
]

# Dataset retention limits. STALE clears uploaded datasets older than the TTL;
# MAX_DATASETS caps the size of the LRU-style in-memory cache.
UPLOAD_TTL_S = int(_env("UPLOAD_TTL_S", "86400"))
MAX_DATASETS = int(_env("MAX_DATASETS", "32"))

# Forecast horizon limits (days) + strategy boundaries.
MIN_FORECAST_DAYS = 1
MAX_FORECAST_DAYS = 730  # 2 years
SHORT_TERM_MAX_DAYS = 7
MEDIUM_TERM_MAX_DAYS = 180

# Classification percentiles for LOW / MEDIUM / HIGH (derived from the uploaded
# historical distribution — never arbitrary fixed thresholds).
LOW_PERCENTILE = 33
HIGH_PERCENTILE = 66

# Trend label band: forecasts within ±TREND_STABLE_THRESHOLD_PCT of the
# historical baseline are STABLE; above is INCREASING, below is DECREASING.
# The same band flags a model-diagnostic warning when the forecast mean falls
# significantly below the uploaded baseline.
TREND_STABLE_THRESHOLD_PCT = float(_env(
    "TREND_STABLE_THRESHOLD_PCT",
    "10",
))

# Minimum historical history (days) recommended before a long-term forecast is
# considered reliable.
LONG_TERM_MIN_HISTORY_DAYS = 90
MEDIUM_TERM_MIN_HISTORY_DAYS = 30

# --- Phase 13: festival / holiday awareness -----------------------------------
# Festival window (days before/after the observed festival day) used for both
# historical analysis and forecast incorporation. Configurable.
FESTIVAL_WINDOW_BEFORE = int(_env("FESTIVAL_WINDOW_BEFORE", "3"))
FESTIVAL_WINDOW_AFTER = int(_env("FESTIVAL_WINDOW_AFTER", "3"))

# Minimum number of in-window historical observations before a festival-specific
# effect may be computed or applied. Below this threshold the response reports
# "Insufficient historical household data…" and the forecast is NOT adjusted.
FESTIVAL_MIN_OBSERVATIONS = int(_env("FESTIVAL_MIN_OBSERVATIONS", "12"))

# Classification band (%): >= +THRESHOLD -> HIGHER_THAN_NORMAL, <= -THRESHOLD ->
# LOWER_THAN_NORMAL, otherwise SIMILAR_TO_NORMAL. Applied per household.
FESTIVAL_EFFECT_THRESHOLD_PCT = float(_env("FESTIVAL_EFFECT_THRESHOLD_PCT", "10"))

# Optional JSON file overriding the curated pan-Indian festival calendar
# (documented approximation; override for state/region-specific dates).
FESTIVAL_CALENDAR_JSON = _env("FESTIVAL_CALENDAR_JSON", "")

# --- Agent / LLM (Phase 9) ----------------------------------------------------
# Provider is provider-agnostic. LLM_API_KEY lives ONLY in the backend .env and
# is never exposed to the frontend. "mock" is a keyless deterministic provider
# used for tests/demo (clearly labelled in responses).
LLM_PROVIDER = _env("LLM_PROVIDER", "mock").strip().lower()
LLM_MODEL = _env("LLM_MODEL", "")
LLM_API_KEY = _env("LLM_API_KEY", "")
LLM_BASE_URL = _env("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_TIMEOUT_S = float(_env("LLM_TIMEOUT_S", "60"))
AGENT_MAX_TOOL_ROUNDS = int(_env("AGENT_MAX_TOOL_ROUNDS", "5"))
AGENT_CONVERSATION_TTL_S = float(_env("AGENT_CONVERSATION_TTL_S", "3600"))
AGENT_MAX_MESSAGE_CHARS = int(_env("AGENT_MAX_MESSAGE_CHARS", "2000"))
