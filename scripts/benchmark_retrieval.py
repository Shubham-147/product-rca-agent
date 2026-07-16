#!/usr/bin/env python3
"""Compare dense-only and hybrid precision on known stub alias clusters."""

from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.retrieval.bm25 import BM25Retriever  # noqa: E402
from src.retrieval.dense import DenseRetriever  # noqa: E402
from src.retrieval.embeddings import FakeEmbeddingClient  # noqa: E402
from src.retrieval.hybrid import HybridRetriever  # noqa: E402
from src.retrieval.reranker import FakeReranker  # noqa: E402


CASES = [
    ("checkout start", {"checkout_start", "begin_checkout", "chkout_init"}),
    ("application crash", {"app_crash", "appCrash", "fatal_err"}),
    ("payment failure", {"payment_failure", "paymentFailed", "pay_fail"}),
    ("product view", {"product_view", "productViewed", "pdp_view"}),
    ("order complete", {"order_complete", "purchase", "orderCompleted"}),
]


def run_benchmark(output_path: Path, k: int = 3) -> dict:
    """Run precision@k comparison, save JSON, and return the report."""
    dense = DenseRetriever(FakeEmbeddingClient())
    hybrid = HybridRetriever(BM25Retriever(), dense, FakeReranker(), candidate_k=10)
    rows = []
    for query, relevant in CASES:
        dense_names = [hit.event_name for hit in dense.search(query, k)]
        hybrid_names = [hit.event_name for hit in hybrid.resolve_event(query, k)]
        rows.append(
            {
                "query": query,
                "relevant": sorted(relevant),
                "dense_results": dense_names,
                "hybrid_results": hybrid_names,
                "dense_precision_at_k": len(set(dense_names) & relevant) / k,
                "hybrid_precision_at_k": len(set(hybrid_names) & relevant) / k,
            }
        )
    report = {
        "k": k,
        "cases": rows,
        "dense_mean_precision": sum(r["dense_precision_at_k"] for r in rows)
        / len(rows),
        "hybrid_mean_precision": sum(r["hybrid_precision_at_k"] for r in rows)
        / len(rows),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    destination = PROJECT_ROOT / "data" / "retrieval_benchmark.json"
    result = run_benchmark(destination)
    print(f"Dense-only mean precision@{result['k']}: {result['dense_mean_precision']:.3f}")
    print(f"Hybrid mean precision@{result['k']}: {result['hybrid_mean_precision']:.3f}")
    print(f"Saved comparison to {destination}")

