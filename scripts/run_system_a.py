from __future__ import annotations

import argparse
from pathlib import Path

from agent.systems.system_a import SystemA


def main() -> None:
    p = argparse.ArgumentParser(description="Run the actual System A Vanilla RAG pipeline")
    p.add_argument("--id", default="inst_001")
    p.add_argument("--data", default="data")
    args = p.parse_args()
    task = Path(args.data) / "tasks" / f"task_{args.id}.json"
    result = SystemA().run(task)
    if result.error:
        raise SystemExit(result.error)
    print(result.hypotheses[0].model_dump_json(indent=2))


if __name__ == "__main__":
    main()
