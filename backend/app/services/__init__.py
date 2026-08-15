"""Service layer for the SmartGridAI API.

The service layer imports the Phase 1-6 ``ml/scripts`` modules as libraries.
To make those imports work from any entry point (uvicorn, pytest, python -m),
the scripts directory is added to ``sys.path`` exactly like the test suite does.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "ml" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))