"""Cross-encoder and deterministic fallback taxonomy rerankers."""

from __future__ import annotations

import math
import os
import re
from abc import ABC, abstractmethod

from src.retrieval.models import TaxonomyHit


class Reranker(ABC):
    """Interface for assigning query-aware scores to retrieval candidates."""

    @abstractmethod
    def rerank(
        self, query: str, candidates: list[TaxonomyHit]
    ) -> list[TaxonomyHit]:
        """Return all candidates ordered from most to least relevant."""


class CrossEncoderReranker(Reranker):
    """Real sentence-transformers cross-encoder reranker."""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> None:
        # Lazy import/download keeps offline and sandbox runs on the fake backend.
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(model_name)

    def rerank(
        self, query: str, candidates: list[TaxonomyHit]
    ) -> list[TaxonomyHit]:
        if not candidates:
            return []
        pairs = [
            (query, f"{candidate.event_name} {candidate.description}")
            for candidate in candidates
        ]
        scores = self.model.predict(pairs)
        reranked = [
            candidate.model_copy(update={"score": float(score)})
            for candidate, score in zip(candidates, scores)
        ]
        return sorted(reranked, key=lambda hit: (-hit.score, hit.event_name))


def _tokens(text: str) -> set[str]:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower().replace("_", " ")
    tokens = set(re.findall(r"[a-z0-9]+", text))
    expansions = {
        "begin": "start",
        "init": "start",
        "chkout": "checkout",
        "pay": "payment",
        "fail": "failure",
        "purchase": "order",
        "completed": "complete",
        "failed": "failure",
        "crashed": "crash",
        "viewed": "view",
    }
    return {expansions.get(token, token) for token in tokens}


class FakeReranker(Reranker):
    """Deterministic lexical heuristic for download-free tests.

    It combines query-token coverage with a bounded contribution from the original
    retriever score. It is deliberately simple, not a quality substitute for the real
    cross-encoder.
    """

    def rerank(
        self, query: str, candidates: list[TaxonomyHit]
    ) -> list[TaxonomyHit]:
        query_tokens = _tokens(query)
        reranked: list[TaxonomyHit] = []
        for candidate in candidates:
            name_tokens = _tokens(candidate.event_name)
            document_tokens = _tokens(
                f"{candidate.event_name} {candidate.description}"
            )
            name_overlap = len(query_tokens & name_tokens) / max(len(query_tokens), 1)
            document_overlap = len(query_tokens & document_tokens) / max(
                len(query_tokens), 1
            )
            bounded_source_score = math.tanh(max(candidate.score, 0.0))
            score = 0.55 * name_overlap + 0.35 * document_overlap + 0.10 * bounded_source_score
            reranked.append(candidate.model_copy(update={"score": score}))
        return sorted(reranked, key=lambda hit: (-hit.score, hit.event_name))


def configured_reranker() -> Reranker:
    """Build the backend selected by ``RERANKER_BACKEND``."""
    backend = os.getenv("RERANKER_BACKEND", "fake").strip().lower()
    if backend == "fake":
        return FakeReranker()
    if backend == "cross-encoder":
        model = os.getenv(
            "CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
        )
        return CrossEncoderReranker(model)
    raise ValueError(
        "RERANKER_BACKEND must be 'fake' or 'cross-encoder', " f"not {backend!r}"
    )
