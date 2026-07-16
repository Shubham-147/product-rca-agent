"""Acceptance checks for metrics and the comparative harness."""

import pandas as pd

from src.eval.harness import falsifiable_commitment_check, run_evaluation
from src.eval.metrics import GroundTruthCase, cohort_id_f1
from src.systems.schema import Hypothesis


def test_cohort_f1_uses_user_set_overlap() -> None:
    truth = GroundTruthCase(
        case_id="x", question="q", user_ids=["u1", "u2"],
        mechanism_terms=["cause"], expected_events=["event"], severity_pp=2,
    )
    hypothesis = Hypothesis(
        mechanism="cause", affected_cohort=["u2", "u3"], evidence=[], confidence=0.5
    )
    assert cohort_id_f1(hypothesis, truth) == 0.5


def test_harness_produces_complete_table_and_verdict(tmp_path, capsys) -> None:
    output = tmp_path / "eval_results.csv"
    frame = run_evaluation(output)
    won, verdict = falsifiable_commitment_check(frame)

    assert output.is_file()
    assert list(frame["system"]) == ["System A", "System B", "System C"]
    assert not frame.isna().any().any()
    assert set(pd.read_csv(output).columns) == set(frame.columns)
    assert "SYSTEM C WINS" in verdict if won else "SYSTEM C LOSES" in verdict
    assert "FALSIFIABLE COMMITMENT" in capsys.readouterr().out

