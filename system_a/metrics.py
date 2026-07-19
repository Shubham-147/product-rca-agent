from __future__ import annotations

import json
from pathlib import Path

from eval.scorer import load_gold, score_case

from .schema import SystemAOutput


GPT_INPUT_USD_PER_MILLION = 0.75
GPT_OUTPUT_USD_PER_MILLION = 4.50
EMBEDDING_USD_PER_MILLION = 0.02


def calculate_metrics(data: Path, artifact_root: Path) -> dict:
    """Score saved predictions, then derive reporting metrics from their traces."""
    data = data.resolve()
    artifact_root = artifact_root.resolve()
    pred_dir = artifact_root / "predictions"
    trace_dir = artifact_root / "traces"
    ids = [row["instance_id"] for row in json.loads((data / "warehouses/index.json").read_text())]
    available_ids = [
        iid for iid in ids
        if (pred_dir / f"{iid}.json").is_file() and (trace_dir / f"{iid}.json").is_file()
    ]
    if len(available_ids) < 2:
        raise FileNotFoundError(
            "At least 2 complete prediction/trace pairs are required to calculate metrics; "
            f"found {len(available_ids)}"
        )

    # Validate every prediction before the evaluator is allowed to load gold.
    predictions = {
        iid: SystemAOutput.model_validate_json((pred_dir / f"{iid}.json").read_text())
        for iid in available_ids
    }
    traces = {
        iid: json.loads((trace_dir / f"{iid}.json").read_text())
        for iid in available_ids
    }

    rows: list[dict] = []
    confounder_correct: list[bool] = []
    for iid in available_ids:
        gold = load_gold(data / "ground_truth", iid)
        result = score_case(
            predictions[iid].hypotheses,
            gold,
            str(data / "warehouses" / f"warehouse_{iid}.duckdb"),
        )
        rows.append({"instance_id": iid, **result})
        if gold.is_confounder_trap or gold.is_simpson:
            confounder_correct.append(bool(result["top1_correct"]))

    faults = [row for row in rows if row["has_fault"]]
    no_fault = [row for row in rows if not row["has_fault"]]
    f1s = [row["cohort_f1"] for row in faults if row.get("cohort_f1") is not None]
    timings = [trace["timing"] for trace in traces.values() if trace.get("timing", {}).get("recorded")]
    llm_input = sum(trace["llm"].get("prompt_tokens") or 0 for trace in traces.values())
    llm_output = sum(trace["llm"].get("completion_tokens") or 0 for trace in traces.values())
    embedding_tokens = sum(trace.get("embedding", {}).get("total_tokens") or 0 for trace in traces.values())
    total_cost = (
        llm_input * GPT_INPUT_USD_PER_MILLION / 1_000_000
        + llm_output * GPT_OUTPUT_USD_PER_MILLION / 1_000_000
        + embedding_tokens * EMBEDDING_USD_PER_MILLION / 1_000_000
    )

    def mean(field: str) -> float | None:
        values = [float(t[field]) for t in timings if t.get(field) is not None]
        return sum(values) / len(values) if values else None

    aggregate = {
        "cases": len(rows),
        "fault_cases": len(faults),
        "no_fault_cases": len(no_fault),
        "attribution_top1": sum(bool(r["top1_correct"]) for r in faults) / len(faults) if faults else 0.0,
        "recall_at_3": sum(bool(r["recall_at_3"]) for r in faults) / len(faults) if faults else 0.0,
        "cohort_id_f1": sum(f1s) / len(f1s) if f1s else 0.0,
        "decoy_fp_rate": sum(bool(r["false_positive"]) for r in no_fault) / len(no_fault) if no_fault else 0.0,
        "confounder_resistance": sum(confounder_correct) / len(confounder_correct) if confounder_correct else None,
        "event_resolution_precision": None,
        "event_resolution_recall": None,
        "cost_usd_total": total_cost,
        "cost_usd_per_case": total_cost / len(rows) if rows else None,
        "latency_seconds_per_case": mean("elapsed_seconds"),
        "embedding_latency_seconds_per_case": mean("embedding_elapsed_seconds"),
        "llm_latency_seconds_per_case": mean("llm_elapsed_seconds"),
    }
    report = {
        "system": "System A - Vanilla RAG",
        "aggregate": aggregate,
        "artifacts": {"predictions": len(predictions), "traces": len(traces), "timed_cases": len(timings)},
        "coverage": {
            "available_cases": len(available_ids),
            "indexed_cases": len(ids),
            "missing_cases": [iid for iid in ids if iid not in available_ids],
        },
        "models": {
            "embedding": sorted({t.get("embedding", {}).get("model") for t in traces.values() if t.get("embedding", {}).get("model")}),
            "generation": sorted({t.get("llm", {}).get("model") for t in traces.values() if t.get("llm", {}).get("model")}),
        },
        "token_usage": {"embedding": embedding_tokens, "llm_input": llm_input, "llm_output": llm_output},
        "notes": {"event_resolution": "Unavailable: predictions do not persist resolved event aliases."},
        "cases": rows,
    }
    metrics_path = artifact_root / "metrics.json"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
