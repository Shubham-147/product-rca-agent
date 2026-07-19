from __future__ import annotations

import hashlib
import os
import re
import time

import numpy as np
from openai import OpenAI

from .schema import RetrievedChunk


def chunk_documents(documents: list[tuple[str, str]], size: int = 1400, overlap: int = 180) -> list[dict]:
    chunks: list[dict] = []
    for source, text in documents:
        clean = re.sub(r"\n{3,}", "\n\n", text.strip())
        start = 0
        while start < len(clean):
            end = min(len(clean), start + size)
            if end < len(clean):
                boundary = clean.rfind("\n", start + size // 2, end)
                end = boundary if boundary > start else end
            body = clean[start:end].strip()
            digest = hashlib.sha256(f"{source}:{start}:{body}".encode()).hexdigest()[:12]
            chunks.append({"chunk_id": f"chunk_{digest}", "source": source, "text": body})
            if end >= len(clean):
                break
            start = max(start + 1, end - overlap)
    if not chunks:
        raise ValueError("Chunking produced no content")
    return chunks


def retrieve_once(chunks: list[dict], query: str, top_k: int = 8) -> tuple[list[RetrievedChunk], dict]:
    if not query.strip():
        raise ValueError("Retrieval query cannot be empty")
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required for text-embedding-3-small retrieval")
    model = "text-embedding-3-small"
    client = OpenAI(api_key=key, base_url=os.environ.get("OPENAI_BASE_URL"))
    started = time.perf_counter()
    response = client.embeddings.create(model=model, input=[c["text"] for c in chunks] + [query])
    elapsed = time.perf_counter() - started
    vectors = np.asarray([item.embedding for item in response.data], dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("Embedding API returned a zero-length vector")
    vectors = vectors / norms
    scores = vectors[:-1] @ vectors[-1]
    order = scores.argsort()[::-1][:top_k]
    retrieved = [RetrievedChunk(**chunks[i], score=round(float(scores[i]), 6)) for i in order]
    usage = getattr(response, "usage", None)
    metadata = {"model": model, "input_count": len(chunks) + 1,
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
                "dimensions": int(vectors.shape[1]), "elapsed_seconds": round(elapsed, 3)}
    return retrieved, metadata
