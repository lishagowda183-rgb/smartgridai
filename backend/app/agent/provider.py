"""LLM provider abstraction (Phase 9).

``LLMService`` is the only interface the agent knows. Two implementations:

- ``OpenAICompatibleProvider`` — speaks the OpenAI chat-completions protocol over
  plain HTTP (httpx). Works with OpenAI, Groq, OpenRouter, LM Studio, Ollama, ...
  Provider-specific details (endpoint/headers/payload/parse) are isolated here.
- ``MockProvider`` — deterministic, network-free provider used by pytest and by
  ``LLM_PROVIDER=mock`` (a keyless local demo). It picks registered tools with
  keyword rules and produces a grounded answer by *formatting the real tool
  results* returned by the services — it never fabricates numbers.

The agent treats both identically: call ``chat(messages, tools)`` and handle the
returned ``ProviderResult`` (text and/or tool calls).
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

import httpx

from .. import config as api_config
from ..errors import AgentNotConfiguredError, AgentProviderError
from . import intents

log = logging.getLogger("api.agent.provider")


class ToolCall:
    __slots__ = ("id", "name", "arguments")

    def __init__(self, id: str, name: str, arguments: dict) -> None:
        self.id = id
        self.name = name
        self.arguments = arguments


class ProviderResult:
    __slots__ = ("content", "tool_calls", "model", "mode")

    def __init__(self, content: str | None, tool_calls: list[ToolCall], model: str, mode: str) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self.model = model
        self.mode = mode


class LLMService(ABC):
    mode = "unknown"

    @abstractmethod
    def chat(self, messages: list[dict], tools: list[dict]) -> ProviderResult:
        """Send a chat request; return final text and/or tool calls."""


# ---------------------------------------------------------------------------
# OpenAI-compatible provider (raw httpx, no SDK dependency)
# ---------------------------------------------------------------------------
class OpenAICompatibleProvider(LLMService):
    mode = "live"

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_s: float = 60.0,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_s

    @classmethod
    def from_config(cls) -> "OpenAICompatibleProvider":
        cfg = api_config
        if not cfg.LLM_API_KEY:
            raise AgentNotConfiguredError(
                "The AI Energy Analyst has no LLM API key configured. Set LLM_PROVIDER, "
                "LLM_MODEL and LLM_API_KEY in the backend .env (or set LLM_PROVIDER=mock "
                "for a keyless demo)."
            )
        if not cfg.LLM_MODEL:
            raise AgentNotConfiguredError("LLM_MODEL is not set in the backend .env")
        return cls(
            model=cfg.LLM_MODEL,
            api_key=cfg.LLM_API_KEY,
            base_url=cfg.LLM_BASE_URL,
            timeout_s=cfg.LLM_TIMEOUT_S,
        )

    def chat(self, messages: list[dict], tools: list[dict]) -> ProviderResult:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise AgentProviderError("LLM provider request timed out") from exc
        except httpx.HTTPError as exc:
            raise AgentProviderError(f"LLM provider connection failed: {exc}") from exc

        if resp.status_code != 200:
            raise AgentProviderError(
                f"LLM provider returned HTTP {resp.status_code}: {resp.text[:300]}"
            )
        try:
            body = resp.json()
            message = body["choices"][0]["message"]
        except (ValueError, KeyError, IndexError) as exc:
            raise AgentProviderError("LLM provider returned an unexpected payload") from exc

        content = message.get("content")
        tool_calls: list[ToolCall] = []
        for call in message.get("tool_calls") or []:
            try:
                args = json.loads(call.get("function", {}).get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(call.get("id") or "", call["function"]["name"], args))
        return ProviderResult(content, tool_calls, self.model, self.mode)


# ---------------------------------------------------------------------------
# Deterministic mock provider (tests + keyless demo). Reads tool results.
# ---------------------------------------------------------------------------
MOCK_HOUSEHOLD_TOOLS = {
    "get_active_dataset", "get_household_overview", "get_current_consumption",
    "get_household_classification", "get_user_forecast", "get_festival_outlook",
    "get_user_analytics", "get_user_anomalies", "get_weather",
    "calculate_household_bill", "calculate_household_what_if",
}


class MockProvider(LLMService):
    mode = "mock"

    def __init__(self, model: str = "mock-router") -> None:
        self.model = model

    @classmethod
    def from_config(cls) -> "MockProvider":
        return cls(model=api_config.LLM_MODEL or "mock-router")

    def chat(self, messages: list[dict], tools: list[dict]) -> ProviderResult:
        # Round 2+: tool results are present -> produce a grounded final answer.
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        if tool_msgs:
            return ProviderResult(self._grounded_answer(tool_msgs), [], self.model, self.mode)

        user_messages = [m.get("content") or "" for m in messages if m.get("role") == "user"]
        user = user_messages[-1].strip() if user_messages else ""
        # Pure greetings/thanks/goodbyes NEVER call tools (conversational Phase 4).
        if intents.is_casual_intent(user) or (not intents.contains_energy_signal(user) and intents.looks_casual(user)):
            return ProviderResult(intents.greeting_for(user), [], self.model, self.mode)
        # Clearly off-topic chatter -> friendly reply, no tools.
        if not intents.contains_energy_signal(user):
            return ProviderResult(intents.off_topic_reply(), [], self.model, self.mode)
        home_ctx = _remembered_context(messages)
        calls = self._plan_tools(user, home_ctx)
        return ProviderResult(None, calls, self.model, self.mode)

    # -- tool planning (keyword based, registered tools only) ------------------
    def _plan_tools(self, message: str, home_ctx: dict) -> list[ToolCall]:
        text = message.lower()
        calls: list[ToolCall] = []
        n = 1

        def add(name, args):
            nonlocal n
            calls.append(ToolCall(f"mock-{n}", name, args))
            n += 1

        kwh = _extract_kwh(message, home_ctx)
        msg_kwh = _extract_kwh_from_text(message)
        ctx_kwh = _extract_kwh_from_ctx(home_ctx)

        # Household what-if: custom target kWh ("use 300 instead") or +/-%.
        if "what if" in text:
            if msg_kwh is not None and ctx_kwh is not None and abs(ctx_kwh - msg_kwh) > 1e-9:
                add("calculate_household_what_if",
                    {"consumption_kwh": ctx_kwh, "target_consumption_kwh": msg_kwh})
            else:
                change = _extract_percent(text)
                if kwh is not None:
                    add("calculate_household_what_if", {"consumption_kwh": kwh, "change_percent": change})
            return calls

        # Festival outlook (must come before the generic overview fallback).
        if "festival" in text or "diwali" in text or "holi" in text or "pongal" in text or "onam" in text:
            add("get_festival_outlook", {})
            return calls

        # "Is my consumption high?" -> classification (from the deterministic engine).
        if any(w in text for w in ("is my usage high", "is my consumption high",
                                   "am i using too much", "my usage high", "my consumption high",
                                   "too much electricity", "status of my", "classification",
                                   "too high", "is it high", "compare to normal",
                                   "why is my usage high", "why is my consumption high",
                                   "why do i use so much")):
            add("get_household_classification", {})
            return calls

        # "Why do I use more on Sundays?" -> usage patterns (never causation).
        if any(w in text for w in ("why do i use", "why do i consume", "why is my usage")):
            add("get_user_analytics", {})
            return calls

        # "What is my current consumption?" -> newest reading straight from data.
        if any(w in text for w in ("current consumption", "current usage", "latest reading",
                                   "latest usage", "how much am i using right now",
                                   "my latest", "current reading")):
            add("get_current_consumption", {})
            return calls

        # Vague festival follow-up with a remembered festival ("what about the next one?").
        if (home_ctx or {}).get("last_festival") and any(w in text for w in
                ("next one", "the next", "after that", "that one", "again")):
            add("get_festival_outlook", {})
            return calls

        # Explicit forecast request (most specific before generic overview).
        if "forecast" in text or "predict" in text or "how much energy will" in text \
                or "next month" in text or "next week" in text:
            hv, hu = _extract_horizon(message)
            add("get_user_forecast", {"horizon_value": hv, "horizon_unit": hu})
            return calls

        # Household bill for a stated kWh figure
        if kwh is not None and any(w in text for w in ("bill", "reduc", "cost", "what if")):
            if "what if" not in text:
                add("calculate_household_bill", {"consumption_kwh": kwh})
                return calls

        # Household question with no consumption known -> ask (no tools)
        if any(w in text for w in ("my bill", "my electricity bill", "my usage",
                                   "my energy bill", "reduce my", "my consumption", "my bill cost")):
            if kwh is None:
                return calls  # service answers with a clarifying question
            add("calculate_household_bill", {"consumption_kwh": kwh})
            return calls

        # Analytics / patterns / trends
        if any(w in text for w in ("analytics", "pattern", "trend", "peak hour",
                                   "when do i use", "usage patterns", "analysis")):
            add("get_user_analytics", {})
            return calls

        # Anomalies / spikes
        if any(w in text for w in ("anomal", "spike", "unusual", "outlier")):
            add("get_user_anomalies", {})
            return calls

        # Weather-consumption *relationship* (Phase 4.1): correlation analysis
        # from the real overlapping weather — never causation, never fabricated.
        if ("weather" in text and any(w in text for w in
            ("affect", "impact", "relat", "correlat", "due to", "because of",
             "influence"))) or any(w in text for w in ("how does weather",
            "does weather", "how weather")):
            add("get_user_analytics", {})
            return calls

        # "Will the weather increase my electricity usage?" -> forecast + weather.
        if any(w in text for w in ("weather", "hot", "cold", "rain", "temp",
                                   "sunny", "humid", "degrees")) and any(
                w in text for w in ("increase", "raise", "go up", "spike",
                                    "reduc", "decrease", "lower")):
            add("get_weather", {"mode": "forecast"})
            add("get_user_forecast", {"horizon_value": 7, "horizon_unit": "days"})
            return calls

        # Weather question (must come before the overview fallback).
        if "weather" in text or any(w in text for w in ("hot", "cold", "rain", "temperature",
                                                        "humid", "sunny", "degrees")):
            mode = "forecast" if any(w in text for w in ("tomorrow", "forecast", "next")) else "current"
            add("get_weather", {"mode": mode})
            return calls

        # Overview / "how much will I use" / today / tomorrow / week / month
        if any(w in text for w in ("overview", "dashboard", "usage today", "today",
                                   "tomorrow", "this week", "this month",
                                   "how much will i use", "my usage", "my consumption",
                                   "my home", "my house")):
            add("get_household_overview", {})
            return calls

        # Dataset / onboarding question
        if any(w in text for w in ("dataset", "data", "active", "what data")):
            add("get_active_dataset", {})
            return calls

        # Generic household fallback: dashboard overview
        add("get_household_overview", {})
        return calls

    # -- grounded answer (formats REAL tool results only) ----------------------
    def _grounded_answer(self, tool_msgs: list[dict]) -> str:
        results = []
        for m in tool_msgs:
            try:
                payload = json.loads(m.get("content") or "{}")
            except json.JSONDecodeError:
                continue
            name = m.get("name")
            if isinstance(payload, dict) and "error" not in payload and name:
                results.append((name, payload))
        if not results:
            return "I could not retrieve any data to answer that question."

        lines = []
        for name, payload in results:
            desc = _describe_tool_result(name, payload)
            if desc:
                lines.append(desc)

        answer = " ".join(lines).strip()
        answer += (
            " These figures are produced from your uploaded data and the deterministic "
            "household forecasting/billing engines (scope: household, kWh, INR)."
        )
        return answer


def _remembered_context(messages: list[dict]) -> dict | None:
    """Parse the system-injected household context (kWh, tariff, horizon, festival)."""
    for m in messages:
        if m.get("role") == "system":
            content = m.get("content") or ""
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("Remembered household context:"):
                    return _parse_remembered(content)
    return None


def _parse_remembered(content: str) -> dict:
    ctx: dict = {}
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("- monthly_kwh:"):
            ctx["monthly_kwh"] = line.split(":", 1)[1].strip()
        elif line.startswith("- tariff_kwh:"):
            ctx["tariff_kwh"] = line.split(":", 1)[1].strip()
        elif line.startswith("- last_horizon_value:"):
            ctx["last_horizon_value"] = line.split(":", 1)[1].strip()
        elif line.startswith("- last_horizon_unit:"):
            ctx["last_horizon_unit"] = line.split(":", 1)[1].strip()
        elif line.startswith("- last_festival:"):
            ctx["last_festival"] = line.split(":", 1)[1].strip()
    return ctx


def _extract_kwh(message: str, home_ctx: dict | None) -> float | None:
    """Best-effort base kWh: from the message if stated, else remembered."""
    from_text = _extract_kwh_from_text(message)
    if from_text is not None:
        return from_text
    return _extract_kwh_from_ctx(home_ctx)


def _extract_kwh_from_text(message: str) -> float | None:
    import re

    matches = list(re.finditer(r"(\d+(?:\.\d+)?)\s*(?:kwh|units)", message.lower()))
    if not matches:
        return None
    return float(matches[-1].group(1))


def _extract_kwh_from_ctx(home_ctx: dict | None) -> float | None:
    if not home_ctx:
        return None
    import re

    kwh = home_ctx.get("monthly_kwh") or home_ctx.get("kwh")
    m = re.search(r"(\d+(?:\.\d+)?)\s*kwh", str(kwh), flags=re.IGNORECASE)
    return float(m.group(1)) if m else None


def _extract_percent(message: str) -> float:
    import re

    m = re.search(r"(\d+(?:\.\d+)?)\s*%", message.lower())
    if m:
        pct = float(m.group(1))
        return -pct if any(w in message.lower() for w in ("reduce", "cut", "lower", "decrease", "less")) else pct
    return 10.0


_INR = lambda v: f"₹{float(v):,.2f}" if v is not None else "—"


def _fmt(v) -> str:
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if float(x).is_integer():
        return f"{int(x):,}"
    return f"{x:,.2f}"


def _extract_horizon(message: str) -> tuple[int, str]:
    """Best-effort horizon parsing ("next 30 days", "next week", "this month"...).

    Returns a (value, unit) usable by ``get_user_forecast`` (units: days/months/years).
    """
    import re

    text = message.lower()
    m = re.search(r"(?:next|this)\s+(\d{1,3})\s*(day|days|week|weeks|month|months|year|years)\b", text)
    if m:
        val = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("day"):
            return max(1, val), "days"
        if unit.startswith("week"):
            return max(1, val) * 7, "days"
        if unit.startswith("month"):
            return max(1, min(24, val)), "months"
        if unit.startswith("year"):
            return max(1, min(2, val)), "years"
    if "next month" in text or "this month" in text:
        return 1, "months"
    if "next week" in text or "this week" in text:
        return 7, "days"
    if "next year" in text or "this year" in text:
        return 1, "years"
    # Default short-term horizon (matches the dashboard view).
    return 7, "days"


def _describe_tool_result(name: str, r: dict) -> str | None:
    if name == "get_active_dataset":
        if r.get("available"):
            ds = r.get("dataset") or {}
            return (
                f"Your active household dataset is {ds.get('filename', r.get('active_dataset_id'))} "
                f"({ds.get('rows')} {ds.get('frequency')} readings, {ds.get('start_date')} to {ds.get('end_date')})."
            )
        return r.get("message") or "No household consumption data is uploaded yet."
    if name == "get_household_overview":
        if r.get("available") is False:
            return r.get("message")
        week = r.get("week") or {}
        month = r.get("month") or {}
        cur = r.get("current") or {}
        peak = r.get("peak") or {}
        weather = r.get("weather") or {}
        bill = r.get("household_bill") or {}
        parts = []
        if cur.get("value") is not None:
            parts.append(f"your latest reading is {cur['value']} {r.get('unit', 'kWh')}")
        if week.get("total") is not None:
            parts.append(f"you are forecast to use about {week['total']} kWh this week")
        if month.get("total") is not None:
            parts.append(f"and about {month['total']} kWh in the next month")
        if peak.get("value") is not None:
            parts.append(f"with a peak of {peak['value']} {r.get('unit', 'kWh')} at {peak.get('timestamp')}")
        if bill.get("total") is not None:
            parts.append(f"an estimated household bill of {_INR(bill['total'])} for the month")
        if r.get("trend"):
            parts.append(f"trend: {r['trend']}")
        parts.append(f"status {r.get('status')}")
        if weather:
            label = weather.get("label") or weather.get("status")
            parts.append(f"weather: {label}")
            if weather.get("status") != "full":
                note = weather.get("note")
                if note:
                    parts.append(f"note: {note}")
        base = ". ".join(p for p in parts if p) + "."
        model = r.get("model")
        if model:
            base += f" Forecast model: {model}."
        return base or None
    if name == "get_user_forecast":
        if r.get("available") is False:
            return r.get("message")
        summary = r.get("summary") or {}
        peak = r.get("peak") or {}
        base = (
            f"The {r.get('display_label', 'forecast')} predicts an average of "
            f"{summary.get('average')} {r.get('unit', 'kWh')}"
            f" (total {summary.get('total')} {r.get('unit', 'kWh')}), peaking at "
            f"{peak.get('value')} {r.get('unit', 'kWh')} on {peak.get('timestamp')}. "
            f"Model: {r.get('model')}."
        )
        weather = r.get("weather") or {}
        status = weather.get("weather_status") or weather.get("status")
        if status in ("full", "partial"):
            base += (
                f" This forecast is weather-aware ({weather.get('label')}; "
                f"source {weather.get('weather_source')}; features "
                f"{', '.join(weather.get('weather_features_used') or []) or 'none'})."
            )
        elif status == "not_available":
            base += f" {weather.get('weather_note') or weather.get('note') or ''}"
        return base
    if name == "get_user_analytics":
        if r.get("available") is False:
            return r.get("message")
        ph = r.get("peak_hours") or {}
        peaks = ph.get("peak_hours") or []
        an = r.get("anomalies") or {}
        s = "Your usage patterns: "
        if peaks:
            top = peaks[0]
            s += f"your highest-average hour is {top['hour']}:00 (avg {top['mean']} {r.get('unit')})"
        if ph.get("peak_to_average_ratio") is not None:
            s += f", peak-to-average ratio {ph['peak_to_average_ratio']}"
        wc = r.get("weather_correlations") or {}
        if wc.get("available"):
            corr = ["%s: %s (%s)" % (c["variable"], c["pearson"], c["interpretation"])
                    for c in wc.get("correlations") or []]
            s += f", weather correlations over {wc.get('overlap_rows')} overlapping hours: " \
                 + ("; ".join(corr) if corr else "no usable correlations")
        if an.get("available"):
            s += f", and {an.get('count')} statistically unusual reading(s) were detected."
        else:
            s += "."
        return s
    if name == "get_user_anomalies":
        if r.get("available") is False:
            return r.get("message")
        if not r.get("count"):
            return "No statistically unusual consumption readings were detected in your history."
        examples = r.get("anomalies") or []
        ex = ""
        if examples:
            a = examples[-1]
            ex = (f" The most recent is on {a.get('timestamp')} (observed {a.get('observed')} "
                  f"{r.get('unit')} vs a typical {a.get('historical_avg')} {r.get('unit')}).")
        return (
            f"{r.get('count')} unusual reading(s) were detected "
            f"(z-score threshold {r.get('threshold')})." + ex
        )
    if name == "get_weather":
        if "current" in r:
            c = r.get("current") or {}
            temp = c.get("temperature_c")
            if temp is None and c.get("message"):
                return c["message"]
            humid = c.get("humidity_pct")
            parts_w = []
            if temp is not None:
                parts_w.append(f"{temp}°C")
            if humid is not None:
                parts_w.append(f"{humid}% humidity")
            if c.get("precipitation_mm") is not None:
                parts_w.append(f"{c['precipitation_mm']} mm precipitation")
            if c.get("wind_speed_kmh") is not None:
                parts_w.append(f"{c['wind_speed_kmh']} km/h wind")
            return (
                "The current weather observation shows "
                + (", ".join(parts_w) if parts_w else "no reading available")
                + f" ({c.get('condition') or 'condition unknown'})"
                + (f". {r.get('notes')}" if r.get("notes") else ".").rstrip()
            )
        pts = r.get("points") or []
        return f"The weather forecast provides {len(pts)} hourly points (persisted Open-Meteo snapshot)."
    if name == "calculate_household_bill":
        return (
            f"For {r.get('monthly_consumption_kwh')} kWh/month ({r.get('reporting_period')}), "
            f"the household bill is {_INR(r.get('total'))} "
            f"(energy charge {_INR(r.get('energy_charge'))}, tax {_INR(r.get('taxes'))})."
        )
    if name == "calculate_household_what_if":
        if r.get("scenario") == "custom":
            return (
                f"Changing your usage from {r.get('original_consumption_kwh')} kWh to "
                f"{r.get('target_consumption_kwh')} kWh/month would bring your household bill "
                f"from {_INR(r.get('original_bill_total'))} to {_INR(r.get('new_bill_total'))} "
                f"({r.get('difference_pct')}%, {_INR(r.get('difference'))} difference)."
            )
        return (
            f"From {_INR(r.get('original_bill_total'))} at {r.get('original_consumption_kwh')} kWh, "
            f"a {r.get('change_percent')}% consumption change gives {_INR(r.get('new_bill_total'))} "
            f"({r.get('difference_pct')}%, {_INR(r.get('difference'))} difference)."
        )
    if name == "get_current_consumption":
        if r.get("available") is False:
            return r.get("message")
        return (
            f"Your latest household reading is {_fmt(r.get('latest_reading'))} "
            f"{r.get('unit', 'kWh')} at {r.get('latest_timestamp')}, and today's total is "
            f"{_fmt(r.get('today_total'))} {r.get('unit', 'kWh')} "
            f"(trailing {_fmt(r.get('trailing_total'))} {r.get('unit', 'kWh')})."
        )
    if name == "get_household_classification":
        if r.get("available") is False:
            return r.get("message")
        cls = r.get("classification") or {}
        why = r.get("reason") or ""
        base = (
            f"Your household usage is classified as {r.get('status')}: {cls.get('label') or ''} "
            f"- your forecast average is {_fmt(cls.get('forecast_mean'))} "
            f"{r.get('unit', 'kWh')} vs {_fmt(cls.get('historical_mean'))} {r.get('unit', 'kWh')} "
            f"historically ({cls.get('forecast_change_percent')}% change)."
        )
        if cls.get("high_period_percentage") is not None:
            base += (
                f" About {cls.get('high_period_percentage')}% of your history sat above the "
                f"90th-percentile threshold ({cls.get('high_period_count')} high periods)."
            )
        if why:
            base += f" Reasoning: {why}."
        if r.get("trend"):
            base += f" Trend: {r['trend']}."
        weather = r.get("weather") or {}
        weath_status = weather.get("weather_status") or weather.get("status")
        if weath_status in ("full", "partial"):
            base += (
                f" Weather is available for the forecast period "
                f"({weather.get('label')}; source {weather.get('weather_source')}) "
                "and the model includes it as a predictive feature."
            )
        return base
    if name == "get_festival_outlook":
        if r.get("available") is False:
            return r.get("message")
        summary = r.get("summary") or {}
        labels = r.get("classification_labels") or {}
        name = summary.get("next_festival_name")
        date = summary.get("next_festival_date")
        if not name:
            return (
                "No festivals are in the short-term calendar. The dashboard only reports "
                "festival-aware effects when the deterministic calendar has entries."
            )
        effect = summary.get("next_festival_class")
        if effect:
            effect_text = labels.get(effect, effect)
        elif summary.get("insufficient_data"):
            effect_text = "not enough history to estimate a festival-specific effect"
        else:
            effect_text = "no observed effect recorded"
        return (
            f"The household festival outlook for the next {r.get('horizon_days')} days starts with "
            f"{name} on {date}. Based on your OWN data, around {name} you {effect_text}; the "
            f"forecast reflects that observed pattern. This comes from the deterministic "
            f"festival calendar, never from a general assumption that festivals mean high usage."
        )
    return None


def build_provider() -> LLMService:
    """Instantiate the provider configured in the backend .env."""
    provider = (api_config.LLM_PROVIDER or "mock").strip().lower()
    if provider in ("mock", "fake", "dummy"):
        return MockProvider.from_config()
    if provider in ("openai_compatible", "openai", "ollama", "groq", "openrouter"):
        return OpenAICompatibleProvider.from_config()
    raise AgentNotConfiguredError(
        f"Unknown LLM_PROVIDER '{provider}'. Use 'mock' or 'openai_compatible'."
    )