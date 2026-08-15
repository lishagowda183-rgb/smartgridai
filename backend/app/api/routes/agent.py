"""Agent routes: the AI Energy Analyst chat endpoint (Phase 9)."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from ... import config as api_config
from ...agent import service as agent_service
from ...errors import (
    AgentNotConfiguredError,
    AgentProviderError,
    AgentToolValidationError,
)
from ...schemas import AgentChatRequest, AgentChatResponse

router = APIRouter(prefix="/agent", tags=["agent"])
log = logging.getLogger("api.agent.route")


@router.post(
    "/chat",
    response_model=AgentChatResponse,
    summary="Ask the AI Energy Analyst a question (grounded tool-calling)",
    responses={
        503: {"description": "Agent/LLM not configured"},
        502: {"description": "LLM provider or tool failure"},
        422: {"description": "Invalid message or tool arguments"},
    },
)
def chat(body: AgentChatRequest) -> AgentChatResponse:
    """Run the agent: LLM -> registered tools -> real results -> grounded answer.

    The message is validated by the Pydantic schema (non-empty, <= 2000 chars).
    LLM failures, tool failures and missing configuration map to structured
    errors instead of crashing.
    """
    try:
        svc = agent_service.service()
    except AgentNotConfiguredError as exc:
        log.warning("agent not configured: %s", exc.message)
        raise exc

    try:
        response = svc.chat(body.message, conversation_id=body.conversation_id)
    except AgentToolValidationError as exc:
        raise exc
    except AgentProviderError as exc:
        raise exc
    return AgentChatResponse(**response)