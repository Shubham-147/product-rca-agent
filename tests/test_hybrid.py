"""Acceptance coverage for reranking, hybrid resolution, and benchmarking."""

import json

from scripts.benchmark_retrieval import run_benchmark
from src.retrieval.bm25 import BM25Retriever
from src.retrieval.dense import DenseRetriever
from src.retrieval.embeddings import FakeEmbeddingClient
from src.retrieval.hybrid import HybridRetriever
from src.retrieval.reranker import FakeReranker


def test_hybrid_deduplicates_and_reranks() -> None:
    retriever = HybridRetriever(
        BM25Retriever(),
        DenseRetriever(FakeEmbeddingClient()),
        FakeReranker(),
    )
    hits = retriever.resolve_event("checkout start", k=5)
    names = [hit.event_name for hit in hits]

    assert names[0] == "checkout_start"
    assert "chkout_init" in names
    assert len(names) == len(set(names))
    assert all(hits[index].score >= hits[index + 1].score for index in range(4))


def test_benchmark_saves_dense_vs_hybrid_comparison(tmp_path) -> None:
    output = tmp_path / "benchmark.json"
    report = run_benchmark(output)

    assert output.is_file()
    assert json.loads(output.read_text()) == report
    assert len(report["cases"]) >= 5
    assert report["hybrid_mean_precision"] >= report["dense_mean_precision"]

