from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load repository-local configuration for CLI and module callers. Existing shell
# environment values take precedence because override=False.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from .llm import generate_once
from .loaders import load_corpus, load_task
from .preprocess import build_event_summary
from .retrieval import chunk_documents, retrieve_once


def run_case(data_root: Path, instance_id: str, output_root: Path, top_k: int = 12) -> dict:
    pipeline_started = time.perf_counter()
    data_root = data_root.resolve(); output_root = output_root.resolve()
    task = load_task(data_root / "tasks" / f"task_{instance_id}.json", data_root)
    if task["instance_id"] != instance_id:
        raise ValueError(f"Task instance mismatch: expected {instance_id}")
    docs = load_corpus(data_root / "corpus", data_root)
    taxonomy = next(text for source, text in docs if source.endswith("events.jsonl"))
    summary = build_event_summary(data_root / "warehouses" / f"warehouse_{instance_id}.duckdb",
                                  data_root, taxonomy, task["changepoint_day"])
    docs.append((f"derived/{instance_id}_telemetry_summary.txt", summary))
    chunks = chunk_documents(docs)
    query = task["question"] + ("\nFind evidence about telemetry baseline recent checkout latency cold start "
                                "crash payment failure api error and affected cohort os device geo channel.")
    retrieved, embedding_usage = retrieve_once(chunks, query, top_k=top_k)
    context = "\n\n".join(f"[{c.chunk_id}] source={c.source} score={c.score}\n{c.text}" for c in retrieved)
    prediction, usage = generate_once(instance_id, query, context)
    valid_ids = {c.chunk_id for c in retrieved}
    cited = {token.strip("[]().,;:") for h in prediction.hypotheses for e in h.evidence for token in e.claim.split() if token.startswith("chunk_")}
    unsupported = cited - valid_ids
    if unsupported:
        raise ValueError(f"Prediction cites chunks that were not retrieved: {sorted(unsupported)}")
    output_root.mkdir(parents=True, exist_ok=True)
    pred_path = output_root / "predictions" / f"{instance_id}.json"; pred_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path = output_root / "traces" / f"{instance_id}.json"; trace_path.parent.mkdir(parents=True, exist_ok=True)
    pred_path.write_text(prediction.model_dump_json(indent=2) + "\n")
    pipeline_elapsed = time.perf_counter() - pipeline_started
    trace = {"instance_id": instance_id, "created_at": datetime.now(timezone.utc).isoformat(),
             "retrieval_mode": "single_query_dense", "query": query, "top_k": top_k,
             "chunk_count": len(chunks), "embedding": embedding_usage,
             "retrieved": [c.model_dump() for c in retrieved], "llm": usage,
             "timing": {"elapsed_seconds": round(pipeline_elapsed, 3),
                        "embedding_elapsed_seconds": embedding_usage["elapsed_seconds"],
                        "llm_elapsed_seconds": usage["elapsed_seconds"], "recorded": True},
             "leakage_checks": {"ground_truth_loaded": False, "forbidden_columns": "none", "unsupported_citations": []}}
    trace_path.write_text(json.dumps(trace, indent=2) + "\n")
    return {"prediction": prediction, "trace": trace, "prediction_path": pred_path, "trace_path": trace_path}


def run(warehouse: str, task: dict):
    data_root = Path(warehouse).resolve().parents[1]
    result = run_case(data_root, task["instance_id"], Path("artifacts/system_a"))
    return result["prediction"].hypotheses
