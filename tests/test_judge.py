"""Acceptance tests for qualitative judging and calibration."""

import json

from scripts.run_judge import run_demo
from src.eval.judge import judge_answer, judge_human_agreement
from src.systems.llm_client import FakeLLMClient
from src.systems.schema import Hypothesis


def test_judge_returns_valid_score_and_rationale() -> None:
    hypothesis = Hypothesis(
        mechanism="Latency caused abandonment.", affected_cohort=["u1"],
        evidence=["One affected user had 8 seconds latency."], confidence=0.8,
    )
    client = FakeLLMClient(default_response=json.dumps({"score": 4, "rationale": "Numbers support the claim; alternatives remain."}))
    result = judge_answer(client, "Why abandonment?", hypothesis)
    assert 1 <= result.score <= 5
    assert result.rationale


def test_stub_judge_human_agreement_runs() -> None:
    agreement = judge_human_agreement()
    assert agreement.sample_count == 5
    assert agreement.exact_match_rate == 0.8
    assert -1 <= agreement.pearson_correlation <= 1


def test_judge_demo_scores_system_outputs(tmp_path) -> None:
    output = tmp_path / "judge_results.json"
    results = run_demo(output)
    assert len(results) == 3
    assert all(1 <= row["score"] <= 5 and row["rationale"] for row in results)
    assert json.loads(output.read_text()) == results

