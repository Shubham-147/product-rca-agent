"""`retrieve_spec` backend — dense RAG over the PRD (and support tickets).

The lower-stakes retrieval surface (not P/R-gated): it feeds the agent the product's
*intent* so it can tell a defect from a design choice — the SLO numbers ("checkout p95
< 2000 ms") that make a latency a regression, and the "upsell is optional" line that
makes a drop innocent. Support tickets are included as realistic **red herrings**
(vague "app feels slow" reports the agent must not over-index on).

Chunking: the PRD splits cleanly at markdown headers, so each `##`/`###` section is one
chunk (a funnel step + its acceptance bar stays together). Each ticket is one chunk.
Embedded once with the shared bge-small model; queried top-k by cosine. Offline build,
in-memory (tiny corpus), deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from .embedder import QUERY_INSTRUCTION, get_embedder

REPO_ROOT = Path(__file__).resolve().parents[2]
PRD_PATH = REPO_ROOT / "data" / "corpus" / "spec" / "prd.md"
TICKETS_DIR = REPO_ROOT / "data" / "corpus" / "spec" / "tickets"

_HEADER = re.compile(r"^#{1,3} ", re.MULTILINE)


@dataclass
class SpecChunk:
    chunk_id: str  # e.g. "prd#2.7" or "ticket_0417"
    source: str    # "prd" | "ticket"
    heading: str
    text: str      # heading + body


@dataclass
class SpecHit:
    chunk_id: str
    source: str
    heading: str
    score: float
    text: str


def _split_prd(md: str) -> list[SpecChunk]:
    """One chunk per markdown section (heading + body up to the next header)."""
    idxs = [m.start() for m in _HEADER.finditer(md)] + [len(md)]
    chunks: list[SpecChunk] = []
    for a, b in zip(idxs, idxs[1:]):
        block = md[a:b].strip()
        if not block:
            continue
        heading = block.splitlines()[0].lstrip("# ").strip()
        num = re.match(r"^(\d+(?:\.\d+)?)", heading)
        cid = f"prd#{num.group(1)}" if num else f"prd#{heading[:20]}"
        chunks.append(SpecChunk(chunk_id=cid, source="prd", heading=heading, text=block))
    return chunks


def _load_tickets() -> list[SpecChunk]:
    out: list[SpecChunk] = []
    if not TICKETS_DIR.exists():
        return out
    for f in sorted(TICKETS_DIR.glob("*.md")):
        text = f.read_text().strip()
        subj = next((l for l in text.splitlines() if l.lower().startswith("subject:")), f.stem)
        out.append(SpecChunk(chunk_id=f.stem, source="ticket",
                             heading=subj.replace("Subject:", "").strip(), text=text))
    return out


def _l2(m: np.ndarray) -> np.ndarray:
    return m / np.clip(np.linalg.norm(m, axis=-1, keepdims=True), 1e-12, None)


class SpecIndex:
    def __init__(self, include_tickets: bool = True):
        self.chunks = _split_prd(PRD_PATH.read_text())
        if include_tickets:
            self.chunks += _load_tickets()
        self.model = get_embedder()
        self.matrix = _l2(np.array(list(self.model.embed([c.text for c in self.chunks]))))

    def query(self, query: str, k: int = 4) -> list[SpecHit]:
        qv = _l2(np.array(list(self.model.embed([QUERY_INSTRUCTION + query]))[0]))
        sims = self.matrix @ qv
        order = np.argsort(-sims)[:k]
        return [
            SpecHit(chunk_id=c.chunk_id, source=c.source, heading=c.heading,
                    score=round(float(sims[i]), 4), text=c.text)
            for i in order for c in [self.chunks[i]]
        ]


@lru_cache(maxsize=1)
def get_spec_index() -> SpecIndex:
    return SpecIndex()


if __name__ == "__main__":
    idx = get_spec_index()
    print(f"{len(idx.chunks)} chunks ({sum(c.source=='prd' for c in idx.chunks)} PRD, "
          f"{sum(c.source=='ticket' for c in idx.chunks)} tickets)\n")
    for q in ["what is the checkout latency SLO?",
              "is the upsell step optional?",
              "why is the event data messy?"]:
        print(f"Q: {q}")
        for h in idx.query(q, k=2):
            print(f"   [{h.score}] {h.chunk_id:14s} {h.heading[:50]}")
        print()
