#!/usr/bin/env python3
"""Run the vanilla RAG baseline offline on three stub symptoms."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.systems.llm_client import FakeLLMClient  # noqa: E402
from src.systems.system_a import SystemA  # noqa: E402

QUESTIONS = [
    "Why did checkout abandonment spike?",
    "Why are older Android users crashing before adding to cart?",
    "Why did payment completion fall for one provider?",
]

FAKE_HYPOTHESIS = json.dumps(
    {
        "mechanism": "A retrieved taxonomy event suggests a plausible funnel failure.",
        "affected_cohort": "Users matching the symptom description; not SQL-derived",
        "evidence": ["Relevant taxonomy names and descriptions were retrieved"],
        "confounders_ruled_out": [],
        "confidence": 0.35,
    }
)


def run_demo(output_path: Path) -> list[dict]:
    """Run three questions and save hypotheses plus explicit grounding status."""
    system = SystemA(FakeLLMClient(default_response=FAKE_HYPOTHESIS))
    records = []
    for question in QUESTIONS:
        hypothesis = system.analyze(question)
        record = {
            "question": question,
            "hypothesis": hypothesis.model_dump(),
            "grounded_in_query_results": False,
            "grounding_note": (
                "System A executed no SQL; affected_cohort is not a computed user set."
            ),
        }
        records.append(record)
        print(f"QUESTION: {question}")
        print(f"HYPOTHESIS: {hypothesis.mechanism}")
        print("GROUNDED IN QUERY RESULTS: false — no SQL or aggregation was executed")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print(f"Saved System A demo to {output_path}")
    return records


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    run_demo(PROJECT_ROOT / "data" / "system_a_demo.json")

