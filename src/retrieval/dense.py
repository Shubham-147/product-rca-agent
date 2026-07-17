"""Chroma-based dense retrieval over the generated event taxonomy."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock
from uuid import uuid4

import chromadb
from chromadb.config import Settings as ChromaSettings

from src.retrieval.bm25 import DEFAULT_TAXONOMY_PATH
from src.retrieval.embeddings import EmbeddingClient, configured_embedding_client
from src.retrieval.models import TaxonomyHit

# Chroma 0.6 can emit ERROR logs from an incompatible optional PostHog telemetry client
# even when anonymized telemetry is disabled. It does not affect retrieval, and disabling
# this specific product-telemetry logger keeps API consoles free of false failures.
logging.getLogger("chromadb.telemetry.product.posthog").disabled = True

_client_lock = Lock()
_shared_ephemeral_client: chromadb.ClientAPI | None = None
CHROMA_PATH = DEFAULT_TAXONOMY_PATH.parent / "chroma"


def _shared_chroma_client() -> chromadb.ClientAPI:
    """Keep one thread-safe, process-wide persistent Chroma client."""
    global _shared_ephemeral_client
    with _client_lock:
        if _shared_ephemeral_client is None:
            CHROMA_PATH.mkdir(parents=True, exist_ok=True)
            _shared_ephemeral_client = chromadb.PersistentClient(
                path=str(CHROMA_PATH),
                settings=ChromaSettings(anonymized_telemetry=False)
            )
        return _shared_ephemeral_client


class DenseRetriever:
    """An in-memory Chroma index using an injected embedding client."""

    def __init__(
        self,
        embedding_client: EmbeddingClient,
        taxonomy_path: Path = DEFAULT_TAXONOMY_PATH,
        chroma_client: chromadb.ClientAPI | None = None,
    ) -> None:
        self.embedding_client = embedding_client
        records = json.loads(Path(taxonomy_path).read_text(encoding="utf-8"))
        self.client = chroma_client or _shared_chroma_client()
        self.collection = self.client.create_collection(
            name=f"taxonomy-{uuid4().hex}", metadata={"hnsw:space": "cosine"}
        )
        documents = [f"{r['event_name']} {r['description']}" for r in records]
        self.collection.add(
            ids=[r["event_name"] for r in records],
            documents=documents,
            metadatas=[{"description": r["description"]} for r in records],
            embeddings=self.embedding_client.embed(documents),
        )

    def search(self, query: str, k: int = 5) -> list[TaxonomyHit]:
        """Return the top ``k`` cosine-similar taxonomy records."""
        if k < 1:
            raise ValueError("k must be at least 1")
        result = self.collection.query(
            query_embeddings=self.embedding_client.embed([query]),
            n_results=min(k, self.collection.count()),
            include=["metadatas", "distances"],
        )
        ids = result["ids"][0]
        distances = result["distances"][0]
        metadata = result["metadatas"][0]
        return [
            TaxonomyHit(
                event_name=event_name,
                score=1.0 - float(distance),
                description=meta["description"],
            )
            for event_name, distance, meta in zip(ids, distances, metadata)
        ]


_default_retriever: DenseRetriever | None = None


def search(query: str, k: int = 5) -> list[TaxonomyHit]:
    """Search with the embedding backend selected by ``EMBEDDING_BACKEND``."""
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = DenseRetriever(configured_embedding_client())
    return _default_retriever.search(query, k)
