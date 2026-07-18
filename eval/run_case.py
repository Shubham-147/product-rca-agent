"""Run one (or all) test case(s): show the question, run a system, score it.

  python -m eval.run_case --id inst_003        # one case, verbose
  python -m eval.run_case --all                # every case, summary table

A test case = task_<id>.json (+ warehouse + corpus) scored against gold_<id>.json.
The `--system` is pluggable; today it defaults to the naive baseline. Swap in
Shubham's agent (or systems A/B/C) by pointing it at any module exposing
`run(warehouse, task) -> list[Hypothesis]`.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from eval.scorer import load_gold, score_case


def _load_system(dotted: str):
    return importlib.import_module(dotted).run


def run_one(data: Path, iid: str, system, verbose: bool) -> dict:
    task = json.loads((data / "tasks" / f"task_{iid}.json").read_text())
    warehouse = str(data / "warehouses" / f"warehouse_{iid}.duckdb")
    gold = load_gold(data / "ground_truth", iid)
    hyps = system(warehouse, task)
    result = score_case(hyps, gold, warehouse)

    if verbose:
        print("=" * 78)
        print(f"TEST CASE: {iid}")
        print("=" * 78)
        print("\n--- THE QUESTION (agent-visible, identical for every case) ---")
        print(task["question"])
        print("\n--- SYSTEM OUTPUT (ranked hypotheses) ---")
        for i, h in enumerate(hyps):
            print(f"  #{i+1} [{h.mechanism_type}] cohort=({h.affected_cohort or '—'}) "
                  f"conf={h.confidence}")
            print(f"      {h.mechanism}")
        print("\n--- GROUND TRUTH (held out) ---")
        print(f"  has_fault={gold.has_fault}  fault={gold.fault_type}  "
              f"cohort=({gold.affected_cohort_predicate or '—'})  "
              f"n_affected={len(gold.affected_user_ids)}  severity~{gold.severity_pp_realised}pp")
        print("\n--- SCORE ---")
        for k, v in result.items():
            print(f"  {k}: {v}")
        print()
    return {"instance_id": iid, **result}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--data", default="data")
    ap.add_argument("--system", default="eval.baseline_agent")
    args = ap.parse_args()

    data = Path(args.data)
    system = _load_system(args.system)

    if args.all:
        index = json.loads((data / "warehouses" / "index.json").read_text())
        rows = [run_one(data, e["instance_id"], system, verbose=False) for e in index]
        print(f"== {args.system} on {len(rows)} cases ==")
        print(f"  {'id':10} {'gold_fault':22} {'top_pred':20} {'top1':5} {'F1':6} {'FP':4}")
        n_fault = top1 = fp = 0
        f1s = []
        for r in rows:
            gf = r.get("gold_fault", "none")
            tp = r.get("top_pred", "-") or "-"
            t1 = "✓" if r.get("top1_correct") else ""
            f1 = r.get("cohort_f1")
            f1s.append(f1) if isinstance(f1, (int, float)) else None
            print(f"  {r['instance_id']:10} {gf:22} {str(tp):20} {t1:5} "
                  f"{'' if f1 is None else f1:<6} {'FP' if r.get('false_positive') else ''}")
            if r.get("has_fault"):
                n_fault += 1
                top1 += int(bool(r.get("top1_correct")))
            if r.get("false_positive"):
                fp += 1
        avg_f1 = round(sum(f1s) / len(f1s), 3) if f1s else 0.0
        print(f"\n  attribution top-1: {top1}/{n_fault} fault cases  |  "
              f"mean cohort-F1: {avg_f1}  |  false positives: {fp}")
        print("  (naive baseline — expected to catch crash/latency, miss the rest)")
    else:
        iid = args.id or "inst_000"
        run_one(data, iid, system, verbose=True)


if __name__ == "__main__":
    main()
