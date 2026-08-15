"""Lightweight conversation context for the AI Energy Analyst (Phase 9).

In-memory, TTL-capped store. Only a short text history plus a small context
slots block (monthly kWh + tariff, last forecast horizon, last festival) is
retained — no sensitive personal data, no full tool payloads. Enough for
follow-ups like "what if I reduce it by 10%?" to reuse the remembered 350 kWh
figure, "for next month instead" to reuse the horizon, or "what about Diwali?"
to stay festival-aware.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

_HISTORY_PAIRS = 6          # user/assistant pairs kept in memory
_KWH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:kwh|units)", re.IGNORECASE)


@dataclass
class Conversation:
    id: str
    messages: list[dict] = field(default_factory=list)
    household_kwh: float | None = None
    household_tariff: str | None = None
    last_horizon_value: int | None = None
    last_horizon_unit: str | None = None
    last_festival: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class ConversationStore:
    """Thread-safe in-memory store with TTL eviction."""

    def __init__(self, ttl_s: float = 3600.0) -> None:
        self._ttl = ttl_s
        self._lock = threading.Lock()
        self._store: dict[str, Conversation] = {}

    def get(self, conversation_id: str) -> Conversation | None:
        if not conversation_id:
            return None
        with self._lock:
            conv = self._store.get(conversation_id)
            if conv is None:
                return None
            if time.time() - conv.updated_at > self._ttl:
                del self._store[conversation_id]
                return None
            return conv

    def create(self, conversation_id: str) -> Conversation:
        with self._lock:
            conv = Conversation(id=conversation_id)
            self._store[conversation_id] = conv
            return conv

    def touch_save(self, conv: Conversation) -> None:
        conv.updated_at = time.time()
        self._prune(conv)
        with self._lock:
            self._store[conv.id] = conv

    @staticmethod
    def _prune(conv: Conversation) -> None:
        pairs = [m for m in conv.messages if m.get("role") in ("user", "assistant")]
        if len(pairs) > _HISTORY_PAIRS * 2:
            keep = pairs[-_HISTORY_PAIRS * 2 :]
            conv.messages = keep


def kwh_in_text(text: str) -> float | None:
    m = _KWH_RE.search(text or "")
    return float(m.group(1)) if m else None