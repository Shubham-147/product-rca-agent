"""Pluggable real and deterministic-offline embedding clients."""

from __future__ import annotations

import hashlib
import math
import os
import re
from abc import ABC, abstractmethod


class EmbeddingClient(ABC):
    """Minimal embedding interface used by dense retrieval."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed each input text into a fixed-width numeric vector."""


class SentenceTransformerEmbeddingClient(EmbeddingClient):
    """Real local embeddings backed by sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        # Lazy import keeps offline fake-embedding tests model-download free.
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()


_CONCEPTS = {
    "begin": "start",
    "started": "start",
    "starting": "start",
    "purchase": "order",
    "purchasing": "order",
    "buy": "order",
    "bought": "order",
    "crashed": "crash",
    "fatal": "crash",
    "termination": "crash",
    "terminated": "crash",
    "failure": "error",
    "failed": "error",
    "rejected": "error",
    "slow": "latency",
    "delayed": "latency",
    "rendered": "render",
    "displayed": "view",
}


class FakeEmbeddingClient(EmbeddingClient):
    """Stable feature-hashed vectors for deterministic offline tests.

    A tiny synonym normalizer gives the fake useful semantic behavior without pretending
    to be a learned model. Features are mapped with BLAKE2 rather than Python's randomized
    process hash, so results are reproducible across machines and runs.
    """

    def __init__(self, dimensions: int = 384) -> None:
        if dimensions < 8:
            raise ValueError("dimensions must be at least 8")
        self.dimensions = dimensions

    @staticmethod
    def _tokens(text: str) -> list[str]:
        text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower().replace("_", " ")
        return [_CONCEPTS.get(token, token) for token in re.findall(r"[a-z0-9]+", text)]

    def embed(self, texts: list[str]) -> list[list[float]]:
        output: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            tokens = self._tokens(text)
            features = tokens + [f"{a}:{b}" for a, b in zip(tokens, tokens[1:])]
            for feature in features:
                digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
                value = int.from_bytes(digest, "big")
                vector[value % self.dimensions] += 1.0 if value & 1 else -1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            output.append([value / norm for value in vector])
        return output


def configured_embedding_client() -> EmbeddingClient:
    """Build the embedding backend selected by environment configuration."""
    backend = os.getenv("EMBEDDING_BACKEND", "fake").strip().lower()
    if backend == "fake":
        return FakeEmbeddingClient()
    if backend == "sentence-transformers":
        model = os.getenv("SENTENCE_TRANSFORMER_MODEL", "all-MiniLM-L6-v2")
        return SentenceTransformerEmbeddingClient(model)
    raise ValueError(
        "EMBEDDING_BACKEND must be 'fake' or 'sentence-transformers', "
        f"not {backend!r}"
    )

