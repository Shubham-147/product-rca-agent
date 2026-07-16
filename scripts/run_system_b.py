#!/usr/bin/env python3
"""Run System B offline through a deterministic Pydantic AI FunctionModel."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart  # noqa: E402
from pydantic_ai.models.function import AgentInfo, FunctionModel  # noqa: E402

from scripts.run_system_a import QUESTIONS  # noqa: E402
from src.systems.system_b import SystemB  # noqa: E402


def _sql_for(question: str) -> tuple[str, str, list[str]]:
    lower = question.lower()
    if "checkout" in lower:
        return (
            "SELECT DISTINCT user_id FROM events WHERE outcome IN ('slow', 'threshold_exceeded') ORDER BY user_id",
            "Checkout latency caused affected sessions to stall or abandon.",
            ["Compared explicit checkout latency outcomes in the event stream."],
        )
    if "android" in lower or "crash" in lower:
        return (
            "SELECT DISTINCT user_id FROM events WHERE outcome = 'crash' AND os = 'Android_10' ORDER BY user_id",
            "A device/OS-specific crash interrupted the funnel before cart activity.",
            ["Restricted crash results to the Android 10 cohort."],
        )
    if "cold" in lower or "home screen" in lower:
        return (
            "SELECT DISTINCT user_id FROM events WHERE outcome = 'home_suppressed' ORDER BY user_id",
            "Cold-start initialization suppresses the home render event.",
            ["Selected explicit home_suppressed outcomes after cold starts."],
        )
    if "shipping" in lower or "disappearing" in lower:
        return (
            "SELECT DISTINCT user_id FROM events WHERE outcome = 'screen_not_rendered' ORDER BY user_id",
            "A shipping-screen backend failure prevents the screen from rendering.",
            ["Selected explicit screen_not_rendered outcomes at shipping."],
        )
    return (
        "SELECT DISTINCT user_id FROM events WHERE outcome = 'provider_error' ORDER BY user_id",
        "A payment-provider error prevented successful completion.",
        ["Selected explicit provider_error outcomes from payment events."],
    )


def offline_react_model(question: str) -> FunctionModel:
    """Drive retrieve → resolve → SQL → typed output using Pydantic AI test support."""
    sql, mechanism, evidence_prefix = _sql_for(question)

    def react(messages: list[Any], info: AgentInfo) -> ModelResponse:
        returns = [
            part
            for message in messages
            for part in getattr(message, "parts", [])
            if isinstance(part, ToolReturnPart)
        ]
        if len(returns) == 0:
            return ModelResponse(parts=[ToolCallPart("_retrieve_tool", {"query": question})])
        if len(returns) == 1:
            return ModelResponse(parts=[ToolCallPart("_resolve_events_tool", {"query": question})])
        if len(returns) == 2:
            return ModelResponse(parts=[ToolCallPart("_run_sql_tool", {"query": sql})])

        sql_records = returns[-1].content
        user_ids = [row["user_id"] for row in sql_records]
        output_tool = info.output_tools[0].name
        return ModelResponse(
            parts=[
                ToolCallPart(
                    output_tool,
                    {
                        "mechanism": mechanism,
                        "affected_cohort": user_ids,
                        "evidence": evidence_prefix
                        + [f"DuckDB returned {len(user_ids)} distinct affected users."],
                        "confounders_ruled_out": [],
                        "confidence": 0.82,
                    },
                )
            ]
        )

    return FunctionModel(react, model_name="offline-react-system-b")


def run_demo(output_path: Path) -> list[dict[str, Any]]:
    """Run the same three symptoms as System A and save grounded results."""
    records = []
    for question in QUESTIONS:
        system = SystemB(model=offline_react_model(question))
        hypothesis = system.analyze(question)
        sql_calls = [call for call in system.deps.tool_calls if call["tool"] == "run_sql"]
        record = {
            "question": question,
            "hypothesis": hypothesis.model_dump(),
            "grounded_in_query_results": bool(sql_calls and hypothesis.affected_cohort),
            "tool_calls": system.deps.tool_calls,
        }
        records.append(record)
        print(f"QUESTION: {question}")
        print(f"AFFECTED USERS: {len(hypothesis.affected_cohort)}")
        print(f"DUCKDB QUERIED: {bool(sql_calls)}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print(f"Saved System B demo to {output_path}")
    return records


if __name__ == "__main__":
    run_demo(PROJECT_ROOT / "data" / "system_b_demo.json")
