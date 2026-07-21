"""Runtime retrieval API — the frozen resolver, loaded once, queried read-only.

Phase 1a proved the resolver offline (see docs/retrieval-pipeline-plan.md §8). This
module is the *freeze*: it builds the full weighted-hybrid resolver a single time
(process-cached) and exposes the two things the rest of the system needs:

  * `resolve_events(query, k)` — the agent tool surface: a query term -> ranked
    canonical candidates + the chosen concept (or `unknown`).
  * `canonical_map(names)` — the analytics bridge: raw warehouse event names ->
    canonical concept, so the compiler can group cursed names into logical funnel steps.

The build is <2 s (TF-IDF fit + 44 embeds), so we cache an in-memory singleton rather
than persist a Chroma index — a measure-first simplification over the original plan.
Runtime resolution uses `leave_one_out=False`: real warehouse names are genuinely
unseen, and known aliases *should* match themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .concepts import build_concepts
from .dense import DenseSignal
from .lexical import AnchorIndex, CharNgramSignal, FuzzySignal
from .resolver import UNKNOWN, Resolver


@lru_cache(maxsize=1)
def get_resolver() -> Resolver:
    """Process-wide singleton: full weighted hybrid (charngram + fuzzy + dense)."""
    index = AnchorIndex(build_concepts())
    signals = [CharNgramSignal(index), FuzzySignal(index), DenseSignal(index)]
    return Resolver(signals)  # DEFAULT_WEIGHTS / thresholds frozen in resolver.py


@dataclass
class EventCandidate:
    name: str  # canonical concept id
    score: float
    source: str = "hybrid"


@dataclass
class ResolveResult:
    query: str
    resolved: str  # canonical concept, or UNKNOWN
    confidence: float
    candidates: list[EventCandidate]


def resolve_events(query: str, k: int = 8) -> ResolveResult:
    """Agent-facing: resolve a query term to ranked canonical event concepts."""
    res = get_resolver().resolve(query, leave_one_out=False, top_n=k)
    cands = [EventCandidate(name=c, score=round(s, 4)) for c, s in res.candidates]
    return ResolveResult(query, res.concept_id, round(res.confidence, 4), cands)


def canonical_map(names: list[str]) -> dict[str, str]:
    """Analytics bridge: map each raw event name to its canonical concept (or UNKNOWN).

    Deterministic and pure; callers cache per warehouse. Distinct names only."""
    r = get_resolver()
    out: dict[str, str] = {}
    for n in set(names):
        out[n] = r.resolve(n, leave_one_out=False).concept_id
    return out


UNKNOWN = UNKNOWN  # re-export for consumers


if __name__ == "__main__":
    for q in ["checkout", "chkout_init", "cart", "cold start", "nonsense_zzz"]:
        r = resolve_events(q, k=3)
        cands = ", ".join(f"{c.name}:{c.score}" for c in r.candidates)
        print(f"  {q:14s} -> {r.resolved:18s} conf={r.confidence}  [{cands}]")
