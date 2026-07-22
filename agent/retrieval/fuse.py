"""Reciprocal Rank Fusion (RRF) of per-signal concept rankings.

RRF combines rankings by *rank position*, not raw score — so a char-ngram cosine and
a fuzzy ratio and a dense cosine (three incomparable scales) can vote together without
any normalization or per-signal calibration. Each signal contributes
`weight / (k + rank)` to every concept it ranks; higher k flattens the contribution of
top ranks (standard k=60).

We keep it deterministic and return, alongside the fused ranking, two abstention cues:
  * `top_raw`   — the winning concept's best raw signal score (is anything actually
                  similar?), and
  * `margin`    — fused separation between #1 and #2 (is the win decisive?).
The resolver turns these into an abstain / `unknown` decision.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Fused:
    ranking: list[tuple[str, float]]  # (concept_id, fused_score), desc
    top_raw: float  # best raw signal score for the #1 concept (max over signals)
    margin: float  # fused[#1] - fused[#2], 0 if only one concept

    @property
    def top(self) -> str | None:
        return self.ranking[0][0] if self.ranking else None


def rrf(
    rankings: dict[str, dict[str, float]],
    weights: dict[str, float] | None = None,
    k: int = 60,
) -> Fused:
    """Fuse {signal_name: {concept_id: raw_score}} into one ranking via weighted RRF."""
    weights = weights or {}
    fused: dict[str, float] = {}
    raw_by_concept: dict[str, float] = {}

    for signal, concept_scores in rankings.items():
        w = weights.get(signal, 1.0)
        ranked = sorted(concept_scores.items(), key=lambda kv: -kv[1])
        for rank, (cid, score) in enumerate(ranked, start=1):
            fused[cid] = fused.get(cid, 0.0) + w / (k + rank)
            raw_by_concept[cid] = max(raw_by_concept.get(cid, 0.0), score)

    order = sorted(fused.items(), key=lambda kv: -kv[1])
    if not order:
        return Fused(ranking=[], top_raw=0.0, margin=0.0)
    top_raw = raw_by_concept[order[0][0]]
    margin = order[0][1] - (order[1][1] if len(order) > 1 else 0.0)
    return Fused(ranking=order, top_raw=top_raw, margin=margin)
