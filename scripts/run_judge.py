#!/usr/bin/env python3
"""Offline qualitative grading demo for saved System B/C outputs."""

from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.eval.judge import (  # noqa: E402
    build_grading_prompt,
    judge_answer,
    judge_human_agreement,
)
from src.systems.llm_client import FakeLLMClient  # noqa: E402
from src.systems.schema import Hypothesis  # noqa: E402


def _samples() -> list[tuple[str, str, Hypothesis, int]]:
    system_b = json.loads((PROJECT_ROOT / "data" / "system_b_demo.json").read_text())
    system_c = json.loads((PROJECT_ROOT / "data" / "system_c_trace.json").read_text())
    return [
        ("System B", row["question"], Hypothesis.model_validate(row["hypothesis"]), 4)
        for row in system_b[:2]
    ] + [
        (
            "System C",
            "Why are older Android users crashing before adding to cart?",
            Hypothesis.model_validate(system_c["final_hypothesis"]),
            5,
        )
    ]


def run_demo(output_path: Path) -> list[dict]:
    samples = _samples()
    responses = {
        build_grading_prompt(symptom, hypothesis): json.dumps(
            {
                "score": score,
                "rationale": (
                    "The mechanism follows from the cited cohort evidence and the answer "
                    "states the limits reflected in its confounder field."
                ),
            }
        )
        for _, symptom, hypothesis, score in samples
    }
    client = FakeLLMClient(responses=responses)
    results = []
    for system, symptom, hypothesis, _ in samples:
        grade = judge_answer(client, symptom, hypothesis)
        results.append({"system": system, "score": grade.score, "rationale": grade.rationale})
        print(f"{system}: {grade.score}/5 — {grade.rationale}")
    output_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    agreement = judge_human_agreement()
    print(
        f"STUB JUDGE–HUMAN AGREEMENT: n={agreement.sample_count}, "
        f"exact={agreement.exact_match_rate:.1%}, r={agreement.pearson_correlation:.3f}"
    )
    return results


if __name__ == "__main__":
    run_demo(PROJECT_ROOT / "data" / "judge_results.json")

