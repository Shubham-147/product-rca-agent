"""Acceptance test for System C's actual falsifier revision loop."""

import json

from scripts.run_system_c import SYMPTOM, run_demo
from src.systems.system_c import SystemC


def test_falsifier_detects_confounder_and_loops_before_report() -> None:
    result = SystemC(max_iterations=3).run(SYMPTOM)
    nodes = [entry["node"] for entry in result.state_trace]
    falsifier_entries = [
        entry for entry in result.state_trace if entry["node"] == "falsifier"
    ]

    assert result.revision_count >= 1
    assert result.confounders_found
    assert "OS confounding" in result.confounders_found[0]
    assert nodes.count("hypothesis_gen") >= 2
    assert len(falsifier_entries) >= 2
    assert falsifier_entries[0]["route"] == "revise"
    assert falsifier_entries[-1]["route"] == "report"
    assert nodes.index("report") > nodes.index("falsifier")
    assert result.final_hypothesis is not None
    assert result.final_hypothesis.affected_cohort
    assert all(
        user_id.startswith("user_")
        for user_id in result.final_hypothesis.affected_cohort
    )


def test_system_c_demo_saves_full_trace(tmp_path) -> None:
    output = tmp_path / "system_c_trace.json"
    payload = run_demo(output)
    assert json.loads(output.read_text()) == payload
    assert len(payload["state_trace"]) >= 11
