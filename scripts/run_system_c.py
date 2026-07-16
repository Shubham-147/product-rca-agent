#!/usr/bin/env python3
"""Run and save the confounder-driven System C revision trace."""

from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.systems.system_c import SystemC  # noqa: E402

SYMPTOM = "Why are older Android users crashing before adding to cart?"


def run_demo(output_path: Path) -> dict:
    result = SystemC(max_iterations=3).run(SYMPTOM)
    payload = result.model_dump()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for index, entry in enumerate(result.state_trace, start=1):
        print(f"{index:02d} {entry['node']}: {json.dumps(entry, sort_keys=True)}")
    print(f"REVISION COUNT: {result.revision_count}")
    print(f"CONFOUNDERS FOUND: {len(result.confounders_found)}")
    print(f"FINAL REPORT: {result.final_hypothesis is not None}")
    print(f"Saved System C trace to {output_path}")
    return payload


if __name__ == "__main__":
    run_demo(PROJECT_ROOT / "data" / "system_c_trace.json")

