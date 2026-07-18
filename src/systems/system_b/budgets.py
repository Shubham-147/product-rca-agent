"""System B's hard tool budgets, backed by the shared guard implementation."""
from __future__ import annotations

from src.config import AppSettings
from src.guardrails import SystemBToolGuard


def build_tool_guard(settings: AppSettings) -> SystemBToolGuard:
    return SystemBToolGuard(
        total=settings.system_b_max_tool_calls,
        retrieval=settings.system_b_max_retrieval_calls,
        analytical=settings.system_b_max_analytical_calls,
        timeout_seconds=settings.tool_timeout_seconds,
    )
