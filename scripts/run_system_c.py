"""Run and score System C on one benchmark instance.

Usage: python -m scripts.run_system_c --id inst_001 --max-cycles 2
"""

from __future__ import annotations

import argparse
import json

from agent.systems.system_c import SystemC
from eval.run_suite import DATA, _score_one


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LangGraph System C on one case")
    parser.add_argument("--id", default="inst_001")
    parser.add_argument("--max-cycles", type=int, default=2)
    args = parser.parse_args()
    task = DATA / "tasks" / f"task_{args.id}.json"
    if not task.exists():
        raise SystemExit(f"Task not found: {task}")
    row = _score_one(SystemC(max_cycles=args.max_cycles), task)
    print(json.dumps(row, indent=2, default=str))


if __name__ == "__main__":
    main()
