"""Intent helpers for the AI Energy Assistant (Phase 4).

Deterministic, provider-independent intent detection for the *conversational*
edges of the assistant:

- ``is_casual_intent`` — pure greetings / thanks / goodbye. These must NEVER
  trigger data tools (no forecast/billing/weather/festival/classification).
- ``greeting_for`` — a natural, friendly greeting/goodbye response (spec style).
- ``off_topic_reply`` — a friendly response for unrelated questions so the agent
  never wastes tool calls on out-of-scope chatter.

The ENERGY gate exists so "hi, what is my bill?" is still routed to billing,
while a bare "hi" is not. These helpers are used both by ``MockProvider`` (the
keyless demo/test router) and by ``AgentService`` (deterministic short-circuit
before any LLM round, so greetings never call tools even with a live provider).
"""

from __future__ import annotations

import re

# Exact-ish casual phrases. Normalization lowercases and strips punctuation so
# "hi!", "bye.", "thanks —" all match.
_CASUAL: set[str] = {
    "hi", "hello", "hey", "hi there", "hello there", "hey there",
    "good morning", "good afternoon", "good evening", "good day",
    "thanks", "thank you", "thank you so much", "thank you very much",
    "bye", "goodbye", "good bye", "see you", "see you later",
    "how are you", "how are you doing", "how's it going", "what's up",
    "greetings", "namaste", "wassup",
}

# Words that indicate the user actually wants energy information even when the
# message *starts* casually ("hi, what's my bill?"). A pure greeting contains
# none of them.
_ENERGY_KEYWORDS: set[str] = {
    "kwh", "kw", "unit", "units", "usage", "consum", "bill", "cost", "price",
    "tariff", "charge", "forecast", "predict", "future", "tomorrow", "next",
    "this week", "this month", "monthly", "weather", "temp", "hot", "cold",
    "rain", "festival", "diwali", "holi", "pongal", "onam", "eid",
    "christmas", "holiday", "celebra", "peak", "anomal", "spike", "unusual",
    "classification", "status", "high", "low", "medium", "energy",
    "electricity", "power", "load", "reading", "consume", "use", "used",
    "uses", "will i", "what if", "affect", "increase", "decrease", "rising",
    "save", "saving", "savings", "data", "dataset", "upload", "analytics",
    "pattern", "trend", "weather", "temperature", "humidity", "bill",
    "current consumption", "overview", "dashboard",
}

_RE_NORMALIZE = re.compile(r"[^a-z0-9 ]+")


def _normalize(message: str) -> str:
    text = (message or "").lower()
    text = _RE_NORMALIZE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_casual_intent(message: str) -> bool:
    """True for a *pure* casual message (no energy ask behind it)."""
    normalized = _normalize(message)
    if normalized not in _CASUAL:
        return False
    return not any(word in normalized for word in _ENERGY_KEYWORDS)


_CASUAL_TOKENS = re.compile(
    r"\b(hi|hello|hey|thanks|thank you|thank u|thanks a lot|thanks a ton|"
    r"thankyou|bye|goodbye|welcome|ok|okay|sure|got it|great|nice|awesome|"
    r"perfect|good night|good morning|good afternoon|good evening|namaste)\b"
)


def looks_casual(message: str) -> bool:
    """Looser check: the message contains a social token (no energy intent)."""
    return bool(_CASUAL_TOKENS.search(_normalize(message)))


def contains_energy_signal(message: str) -> bool:
    """True when the message mentions ANY energy/usage/weather/festival concept."""
    normalized = _normalize(message)
    if not normalized:
        return False
    return any(word in normalized for word in _ENERGY_KEYWORDS)


_GREETINGS = [
    "Hi! 👋 I'm your AI Energy Assistant. I can help you understand your "
    "electricity usage, forecasts, bills, weather and festival-related "
    "consumption. What would you like to know?",
    "Hello! 👋 Great to see you. I can answer questions about your household "
    "energy — usage, forecasts, bills, weather and festivals. Ask away!",
    "Hey there! 👋 I'm here to help with your household energy — from your "
    "latest usage to future forecasts and bills. What would you like to check?",
]

_FAREWELLS = [
    "Goodbye! 👋 Feel free to come back anytime you want to check your energy "
    "usage, forecasts, bills or festivals.",
    "Bye! 👋 Keep saving energy — I'll be here whenever you need me.",
]

_ACKS = [
    "You're welcome! 👍 Anything else about your energy usage, forecasts, "
    "bills, weather or festivals?",
    "Glad I could help! 😊 Let me know if you'd like anything else, such as a "
    "forecast, bill estimate or festival outlook.",
]

_OFF_TOPIC = (
    "I'm focused on household electricity assistance — I can help with your "
    "usage, forecasts, bills, weather and festival-related consumption in kWh "
    "and INR. I'm not able to answer general questions outside that scope."
)


def _pick(options: list[str], message: str) -> str:
    normalized = _normalize(message)
    # Deterministic selection so tests stay stable across a session.
    return options[sum(ord(c) for c in normalized) % len(options)]


def greeting_for(message: str) -> str:
    """Natural response for a causal message (never mentions tools/data)."""
    normalized = _normalize(message)
    if any(word in normalized for word in ("bye", "goodbye", "see you")):
        return _pick(_FAREWELLS, message)
    if any(word in normalized for word in ("thank", "thanks")):
        return _pick(_ACKS, message)
    return _pick(_GREETINGS, message)


def off_topic_reply() -> str:
    return _OFF_TOPIC