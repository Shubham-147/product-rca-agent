"""Phase 4 metrics and the sole reader of blinded evaluation ground truth."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

from pydantic import BaseModel

from src.systems.schema import Hypothesis

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GROUND_TRUTH_PATH = PROJECT_ROOT / "data" / "manifest.json"
SEVERITY_LEVELS = (2, 4, 8, 16)


class GroundTruthCase(BaseModel):
    case_id: str
    question: str
    user_ids: list[str]
    mechanism_terms: list[str]
    expected_events: list[str]
    severity_pp: int | None = None
    is_decoy: bool = False
    has_confounder: bool = False


def load_ground_truth(path: Path = DEFAULT_GROUND_TRUTH_PATH) -> list[GroundTruthCase]:
    """Read blinded ground truth. No retrieval or system module may call this."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = [
        GroundTruthCase(
            case_id=name,
            question=fault["question"],
            user_ids=fault["user_ids"],
            mechanism_terms=fault["mechanism_terms"],
            expected_events=fault["expected_events"],
            severity_pp=fault["severity_pp"],
            has_confounder=fault.get("has_confounder", False),
        )
        for name, fault in raw["faults"].items()
    ]
    decoy = raw["decoy"]
    cases.append(
        GroundTruthCase(
            case_id=decoy["name"],
            question=decoy["question"],
            user_ids=[],
            mechanism_terms=[],
            expected_events=decoy["expected_events"],
            is_decoy=True,
        )
    )
    return cases


def attribution_top1_recall3(
    hypothesis: Hypothesis | None, truth: GroundTruthCase
) -> float:
    """1 when the top reported mechanism contains the planted causal terms."""
    if hypothesis is None or truth.is_decoy or not truth.mechanism_terms:
        return 0.0
    mechanism = hypothesis.mechanism.lower()
    hits = sum(term.lower() in mechanism for term in truth.mechanism_terms)
    return float(hits >= max(1, len(truth.mechanism_terms) - 1))


def cohort_id_f1(hypothesis: Hypothesis | None, truth: GroundTruthCase) -> float:
    """Set F1 between reported user IDs and planted affected user IDs."""
    if hypothesis is None or truth.is_decoy:
        return 0.0
    predicted = (
        set(hypothesis.affected_cohort)
        if isinstance(hypothesis.affected_cohort, list)
        else set()
    )
    expected = set(truth.user_ids)
    if not predicted and not expected:
        return 1.0
    if not predicted or not expected:
        return 0.0
    overlap = len(predicted & expected)
    precision = overlap / len(predicted)
    recall = overlap / len(expected)
    return 2 * precision * recall / (precision + recall) if overlap else 0.0


def cause_vs_symptom_rate(hypothesis: Hypothesis | None, symptom: str) -> float:
    """1 when output states a causal mechanism rather than echoing the symptom."""
    if hypothesis is None:
        return 0.0
    mechanism = hypothesis.mechanism.lower().strip()
    symptom_words = set(symptom.lower().split())
    mechanism_words = set(mechanism.split())
    causal_markers = {"cause", "causes", "failure", "prevents", "suppresses", "latency"}
    is_echo = mechanism_words and len(mechanism_words - symptom_words) < 2
    return float(bool(mechanism_words & causal_markers) and not is_echo)


def false_positive_rate_on_decoys(
    predictions: list[Hypothesis | None], truths: list[GroundTruthCase]
) -> float:
    """Fraction of decoys incorrectly reported as genuine root causes."""
    pairs = [(prediction, truth) for prediction, truth in zip(predictions, truths) if truth.is_decoy]
    if not pairs:
        return 0.0
    return mean(float(prediction is not None) for prediction, _ in pairs)


def confounder_resistance(
    hypothesis: Hypothesis | None, truth: GroundTruthCase
) -> float:
    """1 when a confounded case identifies the stratified causal mechanism."""
    if not truth.has_confounder:
        return 1.0
    if hypothesis is None:
        return 0.0
    text = hypothesis.mechanism.lower()
    return float("android" in text and "crash" in text and "old device hardware directly" not in text)


def event_resolution_precision_recall(
    predicted_events: list[str], truth: GroundTruthCase
) -> tuple[float, float]:
    """Precision and recall of resolved taxonomy names against expected events."""
    predicted = set(predicted_events)
    expected = set(truth.expected_events)
    if not predicted:
        return 0.0, 0.0
    overlap = len(predicted & expected)
    return overlap / len(predicted), overlap / len(expected) if expected else 0.0


def tool_call_accuracy(observed: list[str], expected: list[str]) -> float:
    """Set F1 for tool selection, ignoring repeated calls and order."""
    observed_set, expected_set = set(observed), set(expected)
    if not expected_set:
        return float(not observed_set)
    overlap = len(observed_set & expected_set)
    if not observed_set or not overlap:
        return 0.0
    precision = overlap / len(observed_set)
    recall = overlap / len(expected_set)
    return 2 * precision * recall / (precision + recall)


def cost_per_case(costs_usd: list[float]) -> float:
    """Mean model/tool cost in USD per evaluated case."""
    return mean(costs_usd) if costs_usd else 0.0


def latency_per_case(latencies_seconds: list[float]) -> float:
    """Mean end-to-end wall-clock seconds per evaluated case."""
    return mean(latencies_seconds) if latencies_seconds else 0.0


def detection_vs_severity_curve(
    scores: list[float], truths: list[GroundTruthCase]
) -> dict[int, float]:
    """Mean attribution detection at each planted 2/4/8/16pp severity."""
    curve: dict[int, float] = {}
    for severity in SEVERITY_LEVELS:
        values = [
            score
            for score, truth in zip(scores, truths)
            if not truth.is_decoy and truth.severity_pp == severity
        ]
        curve[severity] = mean(values) if values else 0.0
    return curve

