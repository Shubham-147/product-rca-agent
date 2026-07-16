"""Acceptance tests for the deliberately limited System A baseline."""

import json
import logging

import pytest

from scripts.run_system_a import FAKE_HYPOTHESIS, QUESTIONS, run_demo
from src.retrieval.models import TaxonomyHit
from src.systems.llm_client import FakeLLMClient
from src.systems.schema import Hypothesis
from src.systems.system_a import SystemA


def _stub_resolver(query: str, k: int) -> list[TaxonomyHit]:
    del query, k
    return [
        TaxonomyHit(
            event_name="checkout_start",
            score=1.0,
            description="Checkout flow started",
        )
    ]


@pytest.mark.parametrize("question", QUESTIONS)
def test_system_a_produces_ungrounded_hypothesis(question, caplog) -> None:
    system = SystemA(
        FakeLLMClient(default_response=FAKE_HYPOTHESIS), resolver=_stub_resolver
    )
    with caplog.at_level(logging.WARNING):
        hypothesis = system.analyze(question)

    assert isinstance(hypothesis, Hypothesis)
    assert hypothesis.affected_cohort == (
        "Users matching the symptom description; not SQL-derived"
    )
    assert hypothesis.confounders_ruled_out == []
    assert "not grounded in SQL query results" in caplog.text


def test_system_a_demo_logs_grounding_limit(tmp_path) -> None:
    output_path = tmp_path / "system_a_demo.json"
    records = run_demo(output_path)

    assert len(records) == 3
    assert all(record["grounded_in_query_results"] is False for record in records)
    assert all("no SQL" in record["grounding_note"] for record in records)
    assert json.loads(output_path.read_text()) == records

