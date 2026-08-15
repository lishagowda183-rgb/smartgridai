"""Agentic AI Energy Analyst (Phase 9).

The agent is a thin orchestration layer over the existing Phase 1-8 backend:
it exposes *registered* safe tools (thin adapters over the service layer), asks
an LLM to select and reason over them, and returns a grounded, structured
answer. The LLM is never the source of truth for numerical results.
"""
