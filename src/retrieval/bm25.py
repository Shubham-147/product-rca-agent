"""Lexical BM25 retrieval over event names and descriptions."""

from __future__ import annotations

import json
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

from src.retrieval.models import TaxonomyHit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TAXONOMY_PATH = PROJECT_ROOT / "data" / "taxonomy.json"


def _tokenize(text: str) -> list[str]:
    """Split prose, snake case, and camel case while retaining compact spellings."""
    expanded = re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower()
    parts = re.findall(r"[a-z0-9]+", expanded.replace("_", " "))
    compact = re.findall(r"[a-z0-9]+", expanded)
    return parts + [token for token in compact if token not in parts]


class BM25Retriever:
    """In-memory BM25 index for a taxonomy JSON file."""

    def __init__(self, taxonomy_path: Path = DEFAULT_TAXONOMY_PATH) -> None:
        self.records = json.loads(Path(taxonomy_path).read_text(encoding="utf-8"))
        corpus = [
            _tokenize(f"{record['event_name']} {record['description']}")
            for record in self.records
        ]
        self.index = BM25Okapi(corpus)

    def search(self, query: str, k: int = 5) -> list[TaxonomyHit]:
        """Return the top ``k`` lexical matches."""
        if k < 1:
            raise ValueError("k must be at least 1")
        scores = self.index.get_scores(_tokenize(query))
        ranked = sorted(range(len(scores)), key=lambda i: (-float(scores[i]), i))[:k]
        return [
            TaxonomyHit(
                event_name=self.records[i]["event_name"],
                score=float(scores[i]),
                description=self.records[i]["description"],
            )
            for i in ranked
        ]


_default_retriever: BM25Retriever | None = None


def search(query: str, k: int = 5) -> list[TaxonomyHit]:
    """Search the default generated taxonomy."""
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = BM25Retriever()
    return _default_retriever.search(query, k)

