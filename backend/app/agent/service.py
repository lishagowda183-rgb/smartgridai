"""Agent orchestration service (Phase 9, conversational).

``AgentService.chat`` runs the tool loop: system prompt + history -> LLM ->
registered tools -> real results -> LLM -> grounded structured response. It owns
scope labelling, deterministic data-point extraction, conversation persistence,
a remembered household context (kWh, tariff, last horizon, last festival), and
honest error handling.

Conversational edges (Phase 4): pure greetings are short-circuited BEFORE any
LLM/tool round so they never waste calls; memory slots are injected back into
the system prompt so follow-ups like "what if I reduce it by 10%?" / "for next
month" / "what about Diwali?" reuse remembered context.

Nothing here recomputes ML/weather/analytics/billing values.
"""

from __future__ import annotations

import json
import logging
import time
import uuid

from .. import config as api_config
from ..errors import AgentNotConfiguredError, AgentProviderError, AgentToolValidationError
from ..services import cache
from . import intents, tools
from .provider import LLMService, ProviderResult, build_provider
from .prompts import CLARIFY_HOUSEHOLD_KWH, system_prompt
from .schemas import Conversation, ConversationStore, kwh_in_text

log = logging.getLogger("api.agent")

HOUSEHOLD_TOOLS = {"calculate_household_bill", "calculate_household_what_if"}


class AgentService:
    def __init__(self, provider: LLMService, store: ConversationStore | None = None) -> None:
        self.provider = provider
        self.store = store or ConversationStore(ttl_s=api_config.AGENT_CONVERSATION_TTL_S)

    # --- public ---------------------------------------------------------------
    def chat(self, message: str, conversation_id: str | None = None) -> dict:
        request_id = uuid.uuid4().hex[:8]
        if not conversation_id:
            conversation_id = uuid.uuid4().hex
        t_start = time.perf_counter()

        conv = self.store.get(conversation_id) or self.store.create(conversation_id)
        # remember any kWh stated in the message (used only when a household tool runs)
        stated_kwh = kwh_in_text(message)

        # Conversational short-circuit: pure greetings NEVER reach the LLM/tools.
        if intents.is_casual_intent(message):
            return self._respond(
                request_id, t_start, conversation_id, conv,
                message, intents.greeting_for(message), [], {}, greeting=True,
            )

        messages = self._build_messages(conv, message)
        specs = tools.tool_specs()

        final_text: str | None = None
        used: list[str] = []
        results: dict[str, dict] = {}

        for _round in range(max(1, api_config.AGENT_MAX_TOOL_ROUNDS)):
            result = self._call_provider(messages, specs, request_id)
            if result.content is None and not result.tool_calls:
                # Provider asked us to clarify (mock household case).
                final_text = CLARIFY_HOUSEHOLD_KWH
                break
            if not result.tool_calls:
                final_text = result.content
                break

            assert_messages = {
                "role": "assistant",
                "content": result.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in result.tool_calls
                ],
            }
            messages.append(assert_messages)

            for tc in result.tool_calls:
                tool_started = time.perf_counter()
                try:
                    payload = tools.execute(tc.name, tc.arguments)
                    ok = True
                except AgentToolValidationError as exc:
                    payload = {"error": exc.message}
                    ok = False
                log.info(
                    "request=%s tool=%s ok=%s duration_ms=%.1f",
                    request_id, tc.name, ok, (time.perf_counter() - tool_started) * 1000,
                )
                if ok and tc.name not in used:
                    used.append(tc.name)
                    results[tc.name] = payload
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": json.dumps(payload),
                    }
                )
        else:
            raise AgentProviderError(
                "The agent did not reach a final answer within "
                f"{api_config.AGENT_MAX_TOOL_ROUNDS} tool rounds."
            )

        if final_text is None or not final_text.strip():
            raise AgentProviderError("The agent returned an empty answer.")

        # Persist household context (only real tool results drive it)
        self._update_household_context(conv, used, results, stated_kwh)

        return self._respond(
            request_id, t_start, conversation_id, conv, message,
            final_text, used, results,
        )

    # --- internals ------------------------------------------------------------
    def _call_provider(self, messages, specs, request_id: str) -> ProviderResult:
        t0 = time.perf_counter()
        try:
            result = self.provider.chat(messages, specs)
        except AgentNotConfiguredError:
            raise
        except AgentProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - any provider failure is a typed 502
            log.warning("request=%s provider call failed: %s", request_id, exc)
            raise AgentProviderError(f"LLM provider call failed: {exc}") from exc
        log.info("request=%s provider_call_ms=%.1f tool_calls=%d", request_id,
                 (time.perf_counter() - t0) * 1000, len(result.tool_calls))
        return result

    def _build_messages(self, conv: Conversation, message: str) -> list[dict]:
        remembered = self._remembered_for_prompt(conv)
        system = system_prompt(remembered_context=remembered)
        messages = [{"role": "system", "content": system}]
        for m in conv.messages:
            if m.get("role") in ("user", "assistant"):
                messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": message})
        return messages

    @staticmethod
    def _remembered_for_prompt(conv: Conversation) -> str | None:
        """Serialize the conversation memory slots for the system prompt."""
        parts = ["Remembered household context:"]
        if conv.household_kwh is not None:
            parts.append(f"- monthly_kwh: {conv.household_kwh} kWh")
        if conv.household_tariff is not None:
            parts.append(f"- tariff_kwh: {conv.household_tariff} INR")
        if conv.last_horizon_value is not None:
            parts.append(f"- last_horizon_value: {conv.last_horizon_value} ({conv.last_horizon_unit})")
            parts.append(f"- last_horizon_unit: {conv.last_horizon_unit}")
        if conv.last_festival is not None:
            parts.append(f"- last_festival: {conv.last_festival}")
        return "\n".join(parts) if len(parts) > 1 else None

    def _update_household_context(self, conv, used, results, stated_kwh) -> None:
        for name in HOUSEHOLD_TOOLS:
            if name in results:
                args_kwh = None
                if name == "calculate_household_bill":
                    args_kwh = results[name].get("monthly_consumption_kwh")
                else:
                    args_kwh = results[name].get("original_consumption_kwh")
                if args_kwh is not None:
                    conv.household_kwh = float(args_kwh)
                    conv.household_tariff = results[name].get("tariff")
                return
        if stated_kwh is not None:
            # Remember the number even if the user only stated it, so follow-ups work.
            conv.household_kwh = stated_kwh
        # Conversation memory is driven by real tool results only.
        fcast = results.get("get_user_forecast")
        if fcast and isinstance(fcast.get("horizon"), dict):
            conv.last_horizon_value = fcast["horizon"].get("value")
            conv.last_horizon_unit = fcast["horizon"].get("unit")
        fest = results.get("get_festival_outlook")
        upcoming = (fest or {}).get("upcoming") or []
        if upcoming:
            conv.last_festival = upcoming[0].get("festival_name")

    def _respond(self, request_id, t_start, conversation_id, conv, message,
                 final_text, used, results, greeting: bool = False) -> dict:
        """Persist the exchange and build the API response (shared with the
        component greeting short-circuit).
        """
        # Household-only agent: every registered tool is household scope.
        scope = "household"
        data_points = []
        seen = set()
        for name, payload in results.items():
            for point in tools.extract_points(name, payload):
                key = (point.get("label"), point.get("value"))
                if key in seen:
                    continue
                seen.add(key)
                data_points.append(point)

        conv.messages.append({"role": "user", "content": message})
        conv.messages.append({"role": "assistant", "content": final_text})
        self.store.touch_save(conv)

        response = {
            "answer": final_text,
            "tools_used": used,
            "conversation_id": conversation_id,
            "data_points": data_points,
            "scope": scope,
            "timestamp": cache.utc_now(),
            "model": getattr(self.provider, "model", None),
            "mode": getattr(self.provider, "mode", "unknown"),
        }
        log.info(
            "request=%s conversation=%s round=%s tools=%s scope=%s total_ms=%.1f",
            request_id, conversation_id[:8], "greeting" if greeting else "tool", used, scope,
            (time.perf_counter() - t_start) * 1000,
        )
        return response


_STORE: ConversationStore | None = None


def service() -> AgentService:
    global _STORE
    if _STORE is None:
        _STORE = ConversationStore(ttl_s=api_config.AGENT_CONVERSATION_TTL_S)
    return AgentService(provider=build_provider(), store=_STORE)