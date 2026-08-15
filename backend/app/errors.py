"""Typed API errors mapped to structured JSON responses in main.py."""

from __future__ import annotations


class APIError(Exception):
    status_code: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(APIError):
    status_code = 404
    code = "NOT_FOUND"


class BadRequestError(APIError):
    status_code = 400
    code = "BAD_REQUEST"


# --- Agent (Phase 9) ----------------------------------------------------------
class AgentNotConfiguredError(APIError):
    status_code = 503
    code = "AGENT_NOT_CONFIGURED"


class AgentProviderError(APIError):
    status_code = 502
    code = "LLM_PROVIDER_ERROR"


class AgentToolError(APIError):
    status_code = 502
    code = "AGENT_TOOL_ERROR"


class AgentToolValidationError(APIError):
    status_code = 422
    code = "AGENT_TOOL_VALIDATION"