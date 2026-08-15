"""Start the SmartGridAI Phase 7 API server.

Usage (from the repo root):

    python backend/run.py

Config comes from .env: API_HOST, API_PORT, LOG_LEVEL (see .env.example).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn  # noqa: E402

from backend.app import config as api_config  # noqa: E402


if __name__ == "__main__":
    uvicorn.run(
        "backend.app.main:app",
        host=api_config.API_HOST,
        port=api_config.API_PORT,
        reload=False,
        log_level=api_config.LOG_LEVEL.lower(),
    )