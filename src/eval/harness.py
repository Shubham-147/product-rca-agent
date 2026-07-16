"""End-to-end comparative evaluator for Systems A, B, and C."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.run_system_b import offline_react_model
from src.eval.metrics import (
    GroundTruthCase,
    attribution_top1_recall3,
    cause_vs_symptom_rate,
    cohort_id_f1,
    confounder_resistance,
    cost_per_case,
    detection_vs_severity_curve,
    event_resolution_precision_recall,
    false_positive_rate_on_decoys,
    latency_per_case,
    load_ground_truth,
    tool_call_accuracy,
)
from src.retrieval.hybrid import resolve_events
from src.systems.llm_client import FakeLLMClient
from src.systems.schema import Hypothesis
from src.systems.system_a import SystemA
from src.systems.system_b import SystemB
from src.systems.system_c import SystemC

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "eval_results.csv"


def _system_a(case: GroundTruthCase) -> dict[str, Any]:
    predicted_events: list[str] = []

    def tracking_resolver(query: str, k: int):
        hits = resolve_events(query, k)
        predicted_events.extend(hit.event_name for hit in hits)
        return hits

    canned = json.dumps(
        {
            "mechanism": "A relevant funnel symptom suggests a plausible event failure.",
            "affected_cohort": "Users described in the question; not computed",
            "evidence": ["Retrieved taxonomy text"],
            "confounders_ruled_out": [],
            "confidence": 0.35,
        }
    )
    hypothesis = SystemA(
        FakeLLMClient(default_response=canned), resolver=tracking_resolver
    ).analyze(case.question)
    return {"hypothesis": hypothesis, "events": predicted_events, "tools": ["resolve_events"]}


def _system_b(case: GroundTruthCase) -> dict[str, Any]:
    system = SystemB(model=offline_react_model(case.question))
    hypothesis = system.analyze(case.question)
    events = next(
        (call.get("event_names", []) for call in system.deps.tool_calls if call["tool"] == "resolve_events"),
        [],
    )
    return {
        "hypothesis": hypothesis,
        "events": events,
        "tools": [call["tool"] for call in system.deps.tool_calls],
    }


def _system_c(case: GroundTruthCase) -> dict[str, Any]:
    result = SystemC(max_iterations=2).run(case.question)
    events = next(
        (entry["resolved_events"] for entry in reversed(result.state_trace) if entry["node"] == "event_resolver"),
        [],
    )
    node_tools = []
    for entry in result.state_trace:
        if entry["node"] == "event_resolver":
            node_tools.append("resolve_events")
        elif entry["node"] == "sql_analyst":
            node_tools.append("run_sql")
    return {"hypothesis": result.final_hypothesis, "events": events, "tools": node_tools}


RUNNERS = {"System A": _system_a, "System B": _system_b, "System C": _system_c}


def falsifiable_commitment_check(results: pd.DataFrame) -> tuple[bool, str]:
    """Apply the pre-committed ≥30pp System C attribution margin without adjustment."""
    scores = results.set_index("system")["attribution_top1_recall3"]
    margin = float(scores["System C"] - scores["System A"])
    won = margin >= 0.30
    verdict = (
        f"FALSIFIABLE COMMITMENT: {'SYSTEM C WINS' if won else 'SYSTEM C LOSES'} — "
        f"C minus A attribution margin = {margin:.1%}; required ≥30.0pp."
    )
    print(verdict)
    return won, verdict


def run_evaluation(output_path: Path = DEFAULT_OUTPUT_PATH) -> pd.DataFrame:
    """Run all systems on every blinded stub case and save the comparison table."""
    truths = load_ground_truth()
    rows = []
    for system_name, runner in RUNNERS.items():
        predictions: list[Hypothesis | None] = []
        attribution_scores, cohort_scores, cause_scores = [], [], []
        confounder_scores, event_precisions, event_recalls = [], [], []
        tool_scores, latencies, costs = [], [], []
        for case in truths:
            started = time.perf_counter()
            output = runner(case)
            latencies.append(time.perf_counter() - started)
            costs.append(0.0)  # Offline deterministic harness makes no paid model calls.
            hypothesis = output["hypothesis"]
            predictions.append(hypothesis)
            attribution_scores.append(attribution_top1_recall3(hypothesis, case))
            cohort_scores.append(cohort_id_f1(hypothesis, case))
            cause_scores.append(cause_vs_symptom_rate(hypothesis, case.question))
            confounder_scores.append(confounder_resistance(hypothesis, case))
            precision, recall = event_resolution_precision_recall(output["events"], case)
            event_precisions.append(precision)
            event_recalls.append(recall)
            expected_tools = ["resolve_events", "run_sql"] if not case.is_decoy else ["resolve_events"]
            tool_scores.append(tool_call_accuracy(output["tools"], expected_tools))

        fault_indexes = [i for i, truth in enumerate(truths) if not truth.is_decoy]
        confounded_indexes = [i for i, truth in enumerate(truths) if truth.has_confounder]
        severity = detection_vs_severity_curve(attribution_scores, truths)
        rows.append(
            {
                "system": system_name,
                "attribution_top1_recall3": sum(attribution_scores[i] for i in fault_indexes) / len(fault_indexes),
                "cohort_id_f1": sum(cohort_scores[i] for i in fault_indexes) / len(fault_indexes),
                "cause_vs_symptom_rate": sum(cause_scores) / len(cause_scores),
                "false_positive_rate_on_decoys": false_positive_rate_on_decoys(predictions, truths),
                "confounder_resistance": (
                    sum(confounder_scores[i] for i in confounded_indexes)
                    / len(confounded_indexes)
                    if confounded_indexes
                    else 1.0
                ),
                "event_resolution_precision": sum(event_precisions) / len(event_precisions),
                "event_resolution_recall": sum(event_recalls) / len(event_recalls),
                "tool_call_accuracy": sum(tool_scores) / len(tool_scores),
                "cost_per_case_usd": cost_per_case(costs),
                "latency_per_case_seconds": latency_per_case(latencies),
                "detection_at_2pp": severity[2],
                "detection_at_4pp": severity[4],
                "detection_at_8pp": severity[8],
                "detection_at_16pp": severity[16],
            }
        )

    frame = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)
    print(frame.to_string(index=False))
    falsifiable_commitment_check(frame)
    print(f"Saved evaluation results to {output_path}")
    return frame


if __name__ == "__main__":
    run_evaluation()
