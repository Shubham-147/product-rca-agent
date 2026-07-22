"""Run a system across the whole benchmark and aggregate the scored metrics.

This is the fitness function (design tenet #5): every change is judged here, on the
full set, not on a single hand-picked instance. Reports the metrics from the brief —
attribution top-1, cohort-F1, decoy false-positive rate, fault detection — plus
cost/latency per case (tenet #6). Writes a JSON run manifest for diffing across runs.

Usage:
  ../.venv/bin/python -m eval.run_suite                 # all instances, System B
  ../.venv/bin/python -m eval.run_suite --limit 5       # first 5 (cheap iteration)
  ../.venv/bin/python -m eval.run_suite --workers 4     # parallel LLM calls
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from eval.scorer import load_gold, score_case

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA = REPO_ROOT / "data"
GROUND_TRUTH = DATA / "ground_truth"
RESULTS_DIR = REPO_ROOT / "eval" / "results"

# Approx OpenRouter/OpenAI prices (USD per 1M tokens) for cost reporting. Update per model.
PRICES = {
    "openai/gpt-4o-mini": (0.15, 0.60), "gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4o": (2.50, 10.0), "gpt-4o": (2.50, 10.0),
}


TRACES_DIR = REPO_ROOT / "eval" / "traces"


def _write_trace(res, iid: str) -> None:
    """Persist the ReAct loop for this run (keyless observability)."""
    if res.trace is None:
        return
    from agent.trace import write_trace
    score = None
    write_trace(res.trace, TRACES_DIR, hypotheses=res.hypotheses)


def _score_one(system, task_path: Path) -> dict:
    task = json.loads(task_path.read_text())
    iid = task["instance_id"]
    warehouse = str((DATA / task["warehouse"]).resolve())
    res = system.run(task_path)
    gold = load_gold(GROUND_TRUTH, iid)
    _write_trace(res, iid)
    if res.error:
        return {"instance_id": iid, "error": res.error, "gold_fault": gold.fault_type,
                "has_fault": gold.has_fault, "top_pred": None,
                "top1_correct": False, "cohort_f1": 0.0, "false_positive": False,
                "tokens": res.total_tokens, "latency_s": res.latency_s,
                "input_tokens": res.input_tokens, "output_tokens": res.output_tokens}
    s = score_case(res.hypotheses, gold, warehouse)
    s.update(instance_id=iid, error=None, tokens=res.total_tokens,
             input_tokens=res.input_tokens, output_tokens=res.output_tokens,
             latency_s=res.latency_s, n_tool_calls=res.n_tool_calls,
             top_cohort=res.hypotheses[0].affected_cohort if res.hypotheses else None)
    return s


def aggregate(rows: list[dict], model: str) -> dict:
    fault = [r for r in rows if r.get("has_fault")]
    nofault = [r for r in rows if not r.get("has_fault")]
    n = len(rows)
    pin, pout = PRICES.get(model, (0.0, 0.0))
    cost = sum(r["input_tokens"] * pin + r["output_tokens"] * pout for r in rows) / 1e6
    def mean(xs): return round(sum(xs) / len(xs), 3) if xs else 0.0
    return {
        "n": n,
        "errors": sum(bool(r["error"]) for r in rows),
        "top1_accuracy": mean([r["top1_correct"] for r in rows]),
        "top1_accuracy_faultcases": mean([r["top1_correct"] for r in fault]),
        "cohort_f1_mean_faultcases": mean([r["cohort_f1"] for r in fault]),
        "decoy_fp_rate_nofault": mean([r["false_positive"] for r in nofault]),
        "n_fault": len(fault), "n_nofault": len(nofault),
        "total_tokens": sum(r["tokens"] for r in rows),
        "est_cost_usd": round(cost, 4),
        "mean_latency_s": mean([r["latency_s"] for r in rows]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    from agent.systems.system_b import SystemB
    from agent.config import get_settings
    system = SystemB()
    model = get_settings().model_name

    tasks = sorted((DATA / "tasks").glob("task_inst_*.json"))
    if args.limit:
        tasks = tasks[: args.limit]
    print(f"Running System {system.name} on {len(tasks)} instances "
          f"(model={model}, workers={args.workers})...\n")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(lambda t: _score_one(system, t), tasks))
    rows.sort(key=lambda r: r["instance_id"])

    print(f"  {'instance':11s} {'gold':18s} {'pred':18s} {'top1':5s} {'cohF1':6s} "
          f"{'fp':3s} {'tok':>7s} {'s':>5s}")
    for r in rows:
        pred = (r.get("top_pred") or "-")[:18]
        flag = "ERR" if r["error"] else ("ok" if r["top1_correct"] else "")
        print(f"  {r['instance_id']:11s} {r['gold_fault']:18s} {pred:18s} "
              f"{str(r['top1_correct']):5s} {r['cohort_f1']:<6.3f} "
              f"{str(r['false_positive'])[0]:3s} {r['tokens']:>7d} {r['latency_s']:>5.0f}")

    agg = aggregate(rows, model)
    print("\nAGGREGATE:")
    for k, v in agg.items():
        print(f"  {k:28s} {v}")

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"suite_system_{system.name}.json"
    out.write_text(json.dumps({"model": model, "aggregate": agg, "cases": rows}, indent=2, default=str))
    print(f"\nwritten -> {out}")


if __name__ == "__main__":
    main()
