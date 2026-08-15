"""Agent tests: AI Energy Assistant (household-only, deterministic mock LLM).

The mock provider routes user questions to the *real* registered tools, so these
tests verify tool selection and that numerical claims are grounded in the real,
deterministic backend outputs — with no paid LLM key required. Regional-grid
tools are intentionally absent from the allowlist.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
_SCRIPTS = PROJECT_ROOT / "ml" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from backend.app.agent import tools  # noqa: E402
from backend.app.agent.provider import MockProvider, build_provider  # noqa: E402
from backend.app.agent.schemas import ConversationStore, kwh_in_text  # noqa: E402
from backend.app.agent.service import AgentService  # noqa: E402
from backend.app.services import upload_service  # noqa: E402

HOUSEHOLD_ONLY = sorted(
    [
        "get_active_dataset",
        "get_household_overview",
        "get_current_consumption",
        "get_household_classification",
        "get_user_forecast",
        "get_festival_outlook",
        "get_user_analytics",
        "get_user_anomalies",
        "get_weather",
        "calculate_household_bill",
        "calculate_household_what_if",
    ]
)


def _upload_household() -> str:
    rng = np.random.default_rng(3)
    idx = pd.date_range("2024-01-01", periods=120 * 24, freq="h")
    vals = 400 + 45 * np.sin(2 * np.pi * idx.hour / 24) + rng.normal(0, 8, len(idx))
    df = pd.DataFrame({"timestamp": idx.strftime("%Y-%m-%d %H:%M:%S"),
                       "consumption": vals.round(3)})
    from fastapi.testclient import TestClient
    from backend.app.main import app
    r = TestClient(app).post("/api/v1/forecast/upload",
                             files={"file": ("household_hourly.csv",
                                             df.to_csv(index=False).encode("utf-8"),
                                             "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["dataset_id"]


@pytest.fixture()
def household_ds():
    upload_service.clear_uploads()
    return _upload_household()


@pytest.fixture(scope="module")
def cleared():
    upload_service.clear_uploads()


@pytest.fixture()
def cleared_now():
    upload_service.clear_uploads()


def test_allowed_tool_names_is_household_only():
    names = tools.allowed_tool_names()
    assert names == HOUSEHOLD_ONLY
    assert not {"get_regional_energy_cost", "get_regional_grid_demand",
                "get_forecast", "get_peak_hours", "get_anomalies"} & set(names)


def test_execute_rejects_unknown_tool():
    from backend.app.errors import AgentToolValidationError

    with pytest.raises(AgentToolValidationError):
        tools.execute("execute_arbitrary_python", {})


def test_execute_rejects_unknown_arguments():
    from backend.app.errors import AgentToolValidationError

    with pytest.raises(AgentToolValidationError):
        tools.execute("get_household_overview", {"secret_path": "/etc/passwd"})


# ---------------------------------------------------------------------------
# Tool argument validation + real data (uploaded household dataset only)
# ---------------------------------------------------------------------------
def test_active_dataset_onboarding(cleared):
    out = tools.execute("get_active_dataset", {})
    assert out["available"] is False
    assert "uploaded" in out["message"].lower()


def test_active_dataset_real(household_ds):
    out = tools.execute("get_active_dataset", {})
    assert out["available"] is True
    assert out["active_dataset_id"] == household_ds
    assert out["dataset"]["scope"]["scope"] == "household"


def test_household_overview_real(household_ds):
    out = tools.execute("get_household_overview", {})
    assert out["available"] is True
    assert out["scope"] == "household"
    assert out["week"]["total"] > 0
    assert out["month"]["total"] > 0
    assert out["today"]["value"] > 0
    assert out["household_bill"]["total"] > 0
    assert out["weather"]["status"] != "full"  # never fabricated overlap
    assert out["model"]


def test_user_forecast_real(household_ds):
    out = tools.execute("get_user_forecast", {"horizon_value": 7, "horizon_unit": "days"})
    assert out["available"] is True
    assert out["dataset_id"] == household_ds
    assert out["summary"]["total"] > 0
    assert out["unit"] == "kWh"


def test_user_forecast_validation():
    from backend.app.errors import AgentToolValidationError

    with pytest.raises(AgentToolValidationError):
        tools.execute("get_user_forecast", {"horizon_value": 0, "horizon_unit": "days"})
    with pytest.raises(AgentToolValidationError):
        tools.execute("get_user_forecast", {"horizon_unit": "years"})  # missing value


def test_user_analytics_real(household_ds):
    out = tools.execute("get_user_analytics", {})
    assert out["available"] is True
    assert len(out["by_hour"]) == 24
    assert out["peak_hours"]["peak_to_average_ratio"] > 0


def test_user_anomalies_real(household_ds):
    out = tools.execute("get_user_anomalies", {})
    assert "available" in out
    if out["available"]:
        assert isinstance(out["count"], int) and out["count"] >= 0
    else:
        assert out["message"]


def test_weather_modes():
    cur = tools.execute("get_weather", {"mode": "current"})
    assert "current" in cur
    fcst = tools.execute("get_weather", {"mode": "forecast"})
    assert "points" in fcst
    from backend.app.errors import AgentToolValidationError

    with pytest.raises(AgentToolValidationError):
        tools.execute("get_weather", {"mode": "nope"})


def test_household_bill_is_deterministic():
    out1 = tools.execute("calculate_household_bill", {"consumption_kwh": 350})
    out2 = tools.execute("calculate_household_bill", {"consumption_kwh": 350})
    assert out1["scope"] == "household"
    assert out1["total"] == pytest.approx(2021.25)
    assert out1 == out2
    from backend.app.errors import AgentToolValidationError

    with pytest.raises(AgentToolValidationError):
        tools.execute("calculate_household_bill", {})  # kwh required


def test_household_what_if_uses_backend_results():
    out = tools.execute("calculate_household_what_if", {"consumption_kwh": 350, "change_percent": -10})
    assert out["original_bill_total"] == pytest.approx(2021.25)
    assert out["new_bill_total"] < out["original_bill_total"]
    assert out["difference"] < 0
    plus = tools.execute("calculate_household_what_if", {"consumption_kwh": 350, "change_percent": 10})
    assert plus["new_bill_total"] > plus["original_bill_total"]


def test_current_consumption_real(household_ds):
    out = tools.execute("get_current_consumption", {})
    assert out["available"] is True
    assert out["dataset_id"] == household_ds
    assert out["latest_reading"] > 0
    assert out["today_total"] > 0
    assert out["scope"] == "household"


def test_current_consumption_onboarding(cleared_now):
    out = tools.execute("get_current_consumption", {})
    assert out["available"] is False
    assert "uploaded" in out["message"].lower()


def test_household_classification_real(household_ds):
    out = tools.execute("get_household_classification", {})
    assert out["available"] is True
    assert out["status"].upper() in ("LOW", "MEDIUM", "HIGH")
    cls = out["classification"]
    assert cls["historical_mean"] > 0
    assert cls["forecast_mean"] > 0
    assert out["scope"] == "household"


def test_festival_outlook_real(household_ds):
    out = tools.execute("get_festival_outlook", {})
    assert out["available"] is True
    assert isinstance(out["analysis"], list)   # festival-by-festival observations
    assert isinstance(out["upcoming"], list)
    assert out["summary"]["next_festival_name"] or out["horizon_days"] >= 1
    assert out["scope"] == "household"


def test_festival_outlook_validation():
    from backend.app.errors import AgentToolValidationError

    with pytest.raises(AgentToolValidationError):
        tools.execute("get_festival_outlook", {"horizon_days": 0})
    with pytest.raises(AgentToolValidationError):
        tools.execute("get_festival_outlook", {"horizon_days": 9999})


def test_what_if_custom_target_kwh():
    out = tools.execute("calculate_household_what_if",
                        {"consumption_kwh": 350, "target_consumption_kwh": 300})
    assert out["scenario"] == "custom"
    assert out["target_consumption_kwh"] == 300
    assert out["new_bill_total"] < out["original_bill_total"]
    from backend.app.errors import AgentToolValidationError

    with pytest.raises(AgentToolValidationError):
        tools.execute("calculate_household_what_if", {"consumption_kwh": 350})  # nothing to change


# ---------------------------------------------------------------------------
# Agent service + endpoint integration (mock LLM, uploaded data)
# ---------------------------------------------------------------------------
def _agent() -> AgentService:
    return AgentService(provider=MockProvider(), store=ConversationStore(ttl_s=3600))


def test_agent_onboarding_when_no_data(cleared_now):
    svc = _agent()
    resp = svc.chat("How much electricity does my house use?")
    assert resp["tools_used"] == ["get_household_overview"]
    assert resp["scope"] == "household"
    assert "uploaded" in resp["answer"].lower()
    assert resp["data_points"] == []


def test_agent_overview_question(household_ds):
    svc = _agent()
    resp = svc.chat("Show me my household overview")
    assert resp["tools_used"] == ["get_household_overview"]
    assert resp["scope"] == "household"
    assert resp["data_points"]
    assert any(d["label"] == "This week total" for d in resp["data_points"])
    assert "kWh" in resp["answer"]


def test_agent_forecast_question(household_ds):
    svc = _agent()
    resp = svc.chat("Forecast my consumption for the next 30 days")
    assert resp["tools_used"] == ["get_user_forecast"]
    assert "average" in resp["answer"].lower()
    assert any(d["label"] == "Forecast average" for d in resp["data_points"])


def test_agent_analytics_question(household_ds):
    svc = _agent()
    resp = svc.chat("When do I use the most electricity each day?")
    assert resp["tools_used"] == ["get_user_analytics"]
    assert "peak-to-average" in resp["answer"].lower() or "hour" in resp["answer"].lower()


def test_agent_anomaly_question(household_ds):
    svc = _agent()
    resp = svc.chat("Any unusual electricity spikes in my history?")
    assert resp["tools_used"] == ["get_user_anomalies"]
    assert resp["answer"]


def test_agent_household_bill_and_scope():
    svc = _agent()
    resp = svc.chat("My house uses 350 units. How much is my bill?")
    assert resp["tools_used"] == ["calculate_household_bill"]
    assert resp["scope"] == "household"
    total = next(d for d in resp["data_points"] if d["label"] == "Household bill total")
    assert total["value"] == pytest.approx(2021.25)
    assert "2,021.25" in resp["answer"]
    assert "household" in resp["answer"]


def test_agent_household_asks_for_consumption_when_unknown(cleared):
    svc = _agent()
    resp = svc.chat("What is my electricity bill?")
    assert resp["tools_used"] == []
    assert "kWh" in resp["answer"]


def test_agent_conversation_context_reuses_kwh():
    svc = _agent()
    first = svc.chat("My house uses 350 units. How much is my bill?")
    conv_id = first["conversation_id"]
    resp = svc.chat("What if I reduce it by 10%?", conversation_id=conv_id)
    assert resp["tools_used"] == ["calculate_household_what_if"]
    assert resp["scope"] == "household"
    original = next(d for d in resp["data_points"] if d["label"] == "Original bill")
    assert original["value"] == pytest.approx(2021.25)


def test_agent_grounded_numbers_match_tool_output():
    svc = _agent()
    resp = svc.chat("My house uses 350 units. How much is my bill?")
    assert "2021.25" in resp["answer"].replace(",", "")


# ---------------------------------------------------------------------------
# Phase 4: conversational assistant (greetings, intents, context memory)
# ---------------------------------------------------------------------------
def test_agent_greeting_needs_no_tools(cleared):
    svc = _agent()
    resp = svc.chat("Hi!")
    assert resp["tools_used"] == []
    assert resp["scope"] == "household"
    assert "👋" in resp["answer"]
    assert resp["data_points"] == []


def test_agent_thanks_and_bye_need_no_tools(cleared):
    svc = _agent()
    for msg in ("Thanks!", "Thank you very much", "Bye", "Goodbye"):
        resp = svc.chat(msg)
        assert resp["tools_used"] == []
        assert resp["answer"]


def test_agent_off_topic_reply_no_tools(cleared):
    svc = _agent()
    resp = svc.chat("What's the best pasta recipe?")
    assert resp["tools_used"] == []
    assert "household electricity" in resp["answer"].lower() or "household" in resp["answer"].lower()


def test_agent_festival_question_routes_to_festival_tool(household_ds):
    svc = _agent()
    resp = svc.chat("Will Diwali affect my electricity usage?")
    assert resp["tools_used"] == ["get_festival_outlook"]
    assert resp["answer"]


def test_agent_classification_question_routes(household_ds):
    svc = _agent()
    resp = svc.chat("Is my consumption high compared to normal?")
    assert resp["tools_used"] == ["get_household_classification"]
    assert "classified" in resp["answer"].lower()


def test_agent_current_consumption_routes(household_ds):
    svc = _agent()
    resp = svc.chat("What is my current consumption right now?")
    assert resp["tools_used"] == ["get_current_consumption"]
    assert "latest" in resp["answer"].lower()
    assert any(d["label"] == "Latest reading" for d in resp["data_points"])


def test_agent_next_month_routes_to_forecast(household_ds):
    svc = _agent()
    resp = svc.chat("What will my consumption be next month?")
    assert resp["tools_used"] == ["get_user_forecast"]
    assert any(d["label"] == "Forecast average" for d in resp["data_points"])


def test_agent_next_two_months_persists_horizon(household_ds):
    svc = _agent()
    first = svc.chat("Forecast my consumption for the next 2 months")
    assert first["tools_used"] == ["get_user_forecast"]
    conv = svc.store.get(first["conversation_id"])
    assert conv.last_horizon_value == 2
    assert conv.last_horizon_unit == "months"


def test_agent_greeting_mid_conversation_needs_no_tools(household_ds):
    svc = _agent()
    first = svc.chat("My house uses 350 units. How much is my bill?")
    conv_id = first["conversation_id"]
    resp = svc.chat("Hi!", conversation_id=conv_id)
    assert resp["tools_used"] == []
    assert "👋" in resp["answer"]


def test_agent_save_on_bill_without_kwh_asks_for_consumption(cleared_now):
    svc = _agent()
    resp = svc.chat("How can I reduce my electricity bill?")
    assert resp["tools_used"] == []
    assert "kWh" in resp["answer"]


def test_agent_festival_followup_uses_memory(household_ds):
    svc = _agent()
    first = svc.chat("Will Diwali affect my usage?")
    conv_id = first["conversation_id"]
    conv = svc.store.get(conv_id)
    assert conv.last_festival
    resp = svc.chat("What about the next one after that?", conversation_id=conv_id)
    assert resp["tools_used"] == ["get_festival_outlook"]


def test_agent_weather_tomorrow_routes_to_forecast(household_ds):
    svc = _agent()
    resp = svc.chat("Will it be hot tomorrow?")
    assert resp["tools_used"] == ["get_weather"]
    assert resp["answer"]


def test_extract_points_for_new_tools(household_ds):
    out = tools.execute("get_festival_outlook", {})
    pts = tools.extract_points("get_festival_outlook", out)
    assert any(p["label"] == "Next festival" for p in pts)
    cur = tools.execute("get_current_consumption", {})
    assert any(p["label"] == "Latest reading" for p in tools.extract_points("get_current_consumption", cur))
    cls = tools.execute("get_household_classification", {})
    assert any(p["label"] == "Status" for p in tools.extract_points("get_household_classification", cls))


def test_agent_what_if_custom_kwh_with_memory():
    svc = _agent()
    first = svc.chat("My house uses 350 units. How much is my bill?")
    conv_id = first["conversation_id"]
    resp = svc.chat("What if I use 300 kWh instead?", conversation_id=conv_id)
    assert resp["tools_used"] == ["calculate_household_what_if"]
    assert resp["scope"] == "household"
    assert "300" in resp["answer"]
    original = next(d for d in resp["data_points"] if d["label"] == "Original bill")
    assert original["value"] == pytest.approx(2021.25)


def test_agent_recalls_last_horizon_for_followup(household_ds):
    svc = _agent()
    first = svc.chat("Forecast my consumption for the next 30 days")
    conv_id = first["conversation_id"]
    resp = svc.chat("What about for next week instead?", conversation_id=conv_id)
    assert resp["tools_used"] == ["get_user_forecast"]
    assert any(d["label"] == "Forecast average" for d in resp["data_points"])


def test_agent_conversation_memory_slots_persist(household_ds):
    svc = _agent()
    first = svc.chat("My house uses 350 units. How much is my bill?")
    conv_id = first["conversation_id"]
    conv = svc.store.get(conv_id)
    assert conv.household_kwh == pytest.approx(350.0)
    resp2 = svc.chat("Forecast for the next 30 days", conversation_id=conv_id)
    conv = svc.store.get(conv_id)
    assert conv.last_horizon_value == 30
    assert conv.last_horizon_unit == "days"
    assert conv.household_kwh == pytest.approx(350.0)


def test_system_prompt_injects_remembered_context(household_ds):
    from backend.app.agent.prompts import system_prompt

    svc = _agent()
    first = svc.chat("My house uses 350 units. How much is my bill?")
    conv = svc.store.get(first["conversation_id"])
    messages = svc._build_messages(conv, "What if I reduce it by 10%?")
    system_content = messages[0]["content"]
    assert "Remembered household context" in system_content
    assert "monthly_kwh: 350" in system_content


def test_intents_unit():
    from backend.app.agent import intents

    assert intents.is_casual_intent("hi") is True
    assert intents.is_casual_intent("hi what is my bill") is False
    assert intents.contains_energy_signal("what is my bill") is True
    assert intents.contains_energy_signal("tell me a joke") is False
    assert intents.off_topic_reply()


def test_response_schema_matches_api(household_ds):
    svc = _agent()
    resp = svc.chat("Show me my household overview")
    assert set(("answer", "tools_used", "data_points", "scope", "timestamp", "conversation_id")) <= set(resp)
    assert isinstance(resp["tools_used"], list)
    assert isinstance(resp["data_points"], list)
    for dp in resp["data_points"]:
        assert "label" in dp


def test_agent_does_not_emit_regional_tools(household_ds):
    svc = _agent()
    for question in ("What is the grid demand right now?",
                     "When is the peak grid demand?",
                     "Any regional grid anomalies?",
                     "What is the regional energy cost?"):
        resp = svc.chat(question)
        assert resp["scope"] == "household"
        assert not set(resp["tools_used"]) & {"get_regional_energy_cost", "get_regional_grid_demand",
                                              "get_forecast", "get_peak_hours", "get_anomalies"}


# ---------------------------------------------------------------------------
# Provider config
# ---------------------------------------------------------------------------
def test_build_provider_default_is_mock():
    provider = build_provider()
    assert isinstance(provider, MockProvider)


def test_mock_provider_emits_only_registered_tools(household_ds):
    import backend.app.agent.service as svc_mod

    svc = svc_mod.AgentService(provider=MockProvider(), store=ConversationStore())
    resp = svc.chat("Random question about my energy")
    assert all(t in tools.allowed_tool_names() for t in resp["tools_used"])


def test_kwh_in_text():
    assert kwh_in_text("my house uses 350 units") == 350.0
    assert kwh_in_text("the bill is 120 kwh") == 120.0
    assert kwh_in_text("no numbers here") is None


def test_conversation_store_ttl():
    store = ConversationStore(ttl_s=3600)
    conv = store.create("c1")
    store.touch_save(conv)
    assert store.get("c1") is not None
    assert store.get("missing") is None


# ---------------------------------------------------------------------------
# HTTP endpoint (TestClient) + config/provider failure handling
# ---------------------------------------------------------------------------
from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402
from backend.app.errors import AgentNotConfiguredError, AgentProviderError  # noqa: E402

AGENT_CLIENT = TestClient(app)


def test_agent_chat_endpoint_happy_path(household_ds):
    r = AGENT_CLIENT.post("/api/v1/agent/chat", json={"message": "Show me my household overview"})
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "household"
    assert "get_household_overview" in body["tools_used"]
    assert body["data_points"]


def test_agent_chat_endpoint_household_scope():
    r = AGENT_CLIENT.post("/api/v1/agent/chat", json={"message": "My house uses 350 units. How much is my bill?"})
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "household"
    total = next(d for d in body["data_points"] if d["label"] == "Household bill total")
    assert total["value"] == pytest.approx(2021.25)


def test_agent_chat_endpoint_rejects_bad_input():
    bad = [
        {},
        {"message": ""},
        {"message": "   "},
        {"message": "x" * 2001},
        {"message": "hi", "conversation_id": "a" * 129},
    ]
    for payload in bad:
        r = AGENT_CLIENT.post("/api/v1/agent/chat", json=payload)
        assert r.status_code == 422, payload


def test_missing_llm_config_raises(monkeypatch):
    import backend.app.agent.provider as prov_module

    import backend.app.config as cfg

    monkeypatch.setattr(cfg, "LLM_PROVIDER", "openai_compatible")
    monkeypatch.setattr(cfg, "LLM_API_KEY", "")
    monkeypatch.setattr(cfg, "LLM_MODEL", "gpt-4o-mini")
    with pytest.raises(AgentNotConfiguredError):
        prov_module.build_provider()


def test_unknown_provider_raises(monkeypatch):
    import backend.app.agent.provider as prov_module

    import backend.app.config as cfg

    monkeypatch.setattr(cfg, "LLM_PROVIDER", "nonexistent_provider")
    with pytest.raises(AgentNotConfiguredError):
        prov_module.build_provider()


def test_provider_failure_is_typed():
    svc = AgentService(provider=MockProvider(), store=ConversationStore())

    class FailingProvider(MockProvider):
        def chat(self, messages, tools):
            raise AgentProviderError("boom")

    svc.provider = FailingProvider()
    with pytest.raises(AgentProviderError):
        svc.chat("Show me my household overview")