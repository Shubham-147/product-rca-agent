from __future__ import annotations

import argparse
import json
from pathlib import Path

from system_a.execution import run_cases_parallel
from system_a.pipeline import run_case


def main() -> None:
    p = argparse.ArgumentParser(description="Run the actual System A Vanilla RAG pipeline")
    p.add_argument("--id", default="inst_001")
    p.add_argument("--all", action="store_true")
    p.add_argument("--data", default="data")
    p.add_argument("--output", default="artifacts/system_a")
    p.add_argument("--workers", type=int, default=4, help="Concurrent cases used with --all (1..16)")
    args = p.parse_args()
    data = Path(args.data)
    if args.all:
        ids = [x["instance_id"] for x in json.loads((data / "warehouses" / "index.json").read_text())]
        results = run_cases_parallel(data, ids, Path(args.output), max_workers=args.workers)
    else:
        results = [run_case(data, args.id, Path(args.output))]
    for result in results:
        iid = result["prediction"].instance_id
        print(f"{iid}: {result['prediction'].hypotheses[0].mechanism_type} -> {result['prediction_path']}")


if __name__ == "__main__":
    main()
