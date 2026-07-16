"""Acceptance tests for the typed Pydantic AI ReAct system."""

import json

from scripts.run_system_a import QUESTIONS
from scripts.run_system_b import offline_react_model, run_demo
from src.systems.schema import Hypothesis
from src.systems.system_b import SystemB


def test_system_b_uses_all_tools_and_returns_real_users() -> None:
    question = QUESTIONS[0]
    system = SystemB(model=offline_react_model(question))
    result = system.analyze(question)

    assert isinstance(result, Hypothesis)
    assert isinstance(result.affected_cohort, list)
    assert result.affected_cohort
    assert all(user_id.startswith("user_") for user_id in result.affected_cohort)
    assert [call["tool"] for call in system.deps.tool_calls] == [
        "retrieve",
        "resolve_events",
        "run_sql",
    ]
    assert system.deps.tool_calls[-1]["rows"] == len(result.affected_cohort)


def test_system_b_demo_grounds_same_questions_as_system_a(tmp_path) -> None:
    output = tmp_path / "system_b_demo.json"
    records = run_demo(output)

    assert len(records) == len(QUESTIONS) == 3
    assert all(record["grounded_in_query_results"] for record in records)
    assert all(record["hypothesis"]["affected_cohort"] for record in records)
    assert all(
        any(call["tool"] == "run_sql" for call in record["tool_calls"])
        for record in records
    )
    assert json.loads(output.read_text()) == records

