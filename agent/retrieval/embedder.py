"""Shared local embedding model — loaded once, reused by dense resolution and spec RAG.

Both the event-resolution dense signal and the PRD spec retriever use the same local
bge-small ONNX model. Loading it twice wastes ~130 MB and a second of startup, so both
go through this process-cached accessor.
"""

from __future__ import annotations

from functools import lru_cache

MODEL_NAME = "BAAI/bge-small-en-v1.5"

# bge-v1.5 retrieval convention: prepend this instruction to the QUERY side only
# (documents/passages are embedded raw). Improves asymmetric query→passage recall.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


@lru_cache(maxsize=1)
def get_embedder(model_name: str = MODEL_NAME):
    from fastembed import TextEmbedding

    return TextEmbedding(model_name)
