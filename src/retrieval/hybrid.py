"""Hybrid BM25 + dense candidate retrieval with cross-encoder reranking."""

from __future__ import annotations

from src.retrieval.bm25 import BM25Retriever
from src.retrieval.dense import DenseRetriever
from src.retrieval.embeddings import configured_embedding_client
from src.retrieval.models import TaxonomyHit
from src.retrieval.reranker import Reranker, configured_reranker


class HybridRetriever:
    """Union, deduplicate, and rerank lexical and semantic candidates."""

    def __init__(
        self,
        bm25: BM25Retriever,
        dense: DenseRetriever,
        reranker: Reranker,
        candidate_k: int = 10,
    ) -> None:
        if candidate_k < 1:
            raise ValueError("candidate_k must be at least 1")
        self.bm25 = bm25
        self.dense = dense
        self.reranker = reranker
        self.candidate_k = candidate_k

    def resolve_event(self, query: str, k: int = 5) -> list[TaxonomyHit]:
        """Resolve free text to the top ``k`` taxonomy events."""
        if k < 1:
            raise ValueError("k must be at least 1")
        merged: dict[str, TaxonomyHit] = {}
        for hit in self.bm25.search(query, self.candidate_k) + self.dense.search(
            query, self.candidate_k
        ):
            existing = merged.get(hit.event_name)
            if existing is None or hit.score > existing.score:
                merged[hit.event_name] = hit
        return self.reranker.rerank(query, list(merged.values()))[:k]


_default_retriever: HybridRetriever | None = None


def _default() -> HybridRetriever:
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = HybridRetriever(
            BM25Retriever(),
            DenseRetriever(configured_embedding_client()),
            configured_reranker(),
        )
    return _default_retriever


def resolve_event(query: str, k: int = 5) -> list[TaxonomyHit]:
    """Public hybrid resolver for one event phrase."""
    return _default().resolve_event(query, k)


def resolve_events(query: str, k: int = 5) -> list[TaxonomyHit]:
    """Tool-friendly alias used by Systems B and C."""
    return resolve_event(query, k)

