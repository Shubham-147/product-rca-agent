"""The event resolver — surface name -> canonical concept (or `unknown`).

Composes the signals (lexical now, dense later) over the anchor index, fuses them with
RRF, and applies an abstention rule so a name it cannot place returns `unknown` rather
than a confident wrong answer (precision matters: a mis-resolved event silently
corrupts every downstream funnel/cohort query).

Two consumers, one resolver:
  * the analytics compiler canonicalises raw warehouse event names into logical steps;
  * the `resolve_events` agent tool exposes the ranked candidates for evidence.

`leave_one_out=True` (eval default) masks the query's own anchor so a known alias must
be recognised from its *siblings* — the honest generalization measurement. At runtime
the agent resolves genuinely-unseen names, so `leave_one_out=False`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .concepts import Concept, build_concepts
from .fuse import rrf
from .lexical import AnchorIndex, CharNgramSignal, FuzzySignal, Signal

UNKNOWN = "unknown"

# Default fusion weights + abstention thresholds, chosen on the offline harness
# (eval/run_retrieval.py). Fuzzy is the most reliable signal on this taxonomy, so it
# outvotes the weaker ones; dense adds its lift on the unseen/generalization slice.
# Weighted hybrid: micro-F1 0.911 (vs fuzzy-alone 0.907), unseen 0.933 (vs 0.867).
DEFAULT_WEIGHTS = {"charngram": 2.0, "fuzzy": 3.0, "dense": 1.0}
DEFAULT_MIN_RAW = 0.30  # top concept's best raw signal score must clear this
DEFAULT_MIN_MARGIN = 0.0  # fused #1-#2 separation (0 = disabled by default)


@dataclass
class Resolution:
    query: str
    concept_id: str  # resolved concept, or UNKNOWN
    confidence: float  # top_raw in [0,1]; 0 when abstaining
    candidates: list[tuple[str, float]] = field(default_factory=list)  # ranked (cid, fused)

    @property
    def resolved(self) -> bool:
        return self.concept_id != UNKNOWN


class Resolver:
    def __init__(
        self,
        signals: list[Signal],
        weights: dict[str, float] | None = None,
        rrf_k: int = 60,
        min_raw: float = DEFAULT_MIN_RAW,
        min_margin: float = DEFAULT_MIN_MARGIN,
    ):
        if not signals:
            raise ValueError("Resolver needs at least one signal")
        self.signals = signals
        self.index = signals[0].index
        self.weights = weights or DEFAULT_WEIGHTS
        self.rrf_k = rrf_k
        self.min_raw = min_raw
        self.min_margin = min_margin

    @classmethod
    def lexical(cls, concepts: list[Concept] | None = None, **kw) -> "Resolver":
        """Convenience: char-ngram + fuzzy only (no embedding model needed)."""
        idx = AnchorIndex(concepts or build_concepts())
        return cls([CharNgramSignal(idx), FuzzySignal(idx)], **kw)

    def resolve(self, query: str, leave_one_out: bool = False, top_n: int = 5) -> Resolution:
        exclude = self.index.exclude_for(query) if leave_one_out else set()
        rankings = {s.name: s.rank(query, exclude) for s in self.signals}
        fused = rrf(rankings, self.weights, self.rrf_k)

        if (
            fused.top is None
            or fused.top_raw < self.min_raw
            or fused.margin < self.min_margin
        ):
            return Resolution(query, UNKNOWN, 0.0, fused.ranking[:top_n])
        return Resolution(query, fused.top, fused.top_raw, fused.ranking[:top_n])


if __name__ == "__main__":
    r = Resolver.lexical()
    for q in ["chckt_strt", "BeginCheckout", "add_itm_to_crt", "sssn_strt",
              "prdct_dtl_vw", "zzz_garbage_event"]:
        res = r.resolve(q, leave_one_out=True)
        cands = ", ".join(f"{c}:{s:.3f}" for c, s in res.candidates[:3])
        print(f"  {q:22s} -> {res.concept_id:20s} conf={res.confidence:.2f}  [{cands}]")
