"""Lexical retrieval signals over alias *anchors*.

Every signal scores a query name against each individual known alias (an "anchor"),
then max-pools those to a per-concept score. This shared shape gives us leave-one-out
for free: to resolve a name that is itself a known alias, we mask that one anchor and
force the signal to recognise the concept from its *other* surface forms — turning a
trivial dictionary hit into a genuine generalization test.

Two complementary lexical signals (the design-doc's "hybrid beats dense" thesis):

  * CharNgram — char 2-4 grams over the separator-stripped stream. Sees through
    abbreviations and typos (`chkout` ~ `checkout`, `chckt` ~ `checkout`) because the
    damaged form still shares most of its character ngrams with the clean form.
  * Fuzzy — rapidfuzz edit/token similarity on the normalized token string. A second
    view of the same "cursed string" problem; catches transpositions and partials the
    ngram cosine can rank lower.

No LLM, no gold. Deterministic given the concept vocabulary.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer

from .concepts import Concept
from .normalize import charstream, is_placeholder_name, normalize


class AnchorIndex:
    """Flat list of (alias -> concept) anchors, with concept groupings and a helper
    to find the anchors to mask for a leave-one-out query.

    Dead placeholder names (`beta_checkout_v1`, ...) are dropped: their surface strings
    contradict their description-group and would poison lexical matching. They never
    fire, so they are never queries either — dropping them costs no coverage."""

    def __init__(self, concepts: list[Concept]):
        self.concepts = concepts
        self.anchors: list[str] = []
        self.anchor_concept: list[str] = []
        self.concept_anchor_idx: dict[str, list[int]] = {}
        self._exact: dict[str, list[int]] = {}  # normalized form -> anchor indices
        for c in concepts:
            for a in c.aliases:
                if is_placeholder_name(a):
                    continue
                i = len(self.anchors)
                self.concept_anchor_idx.setdefault(c.concept_id, []).append(i)
                self._exact.setdefault(normalize(a), []).append(i)
                self.anchors.append(a)
                self.anchor_concept.append(c.concept_id)

    def exclude_for(self, query: str) -> set[int]:
        """Anchor indices whose surface string equals the query (leave-one-out mask)."""
        return {i for i, a in enumerate(self.anchors) if a == query}

    def exact_concepts(self, query: str, exclude: set[int] | None = None) -> set[str]:
        """Concepts owning an anchor whose *normalized* form equals the query's.

        An exact normalized match (`sssn_strt` ~ anchor `sssn_strt`) is a lexical
        certainty; the resolver honours it over rank fusion. Excluded anchors
        (leave-one-out) don't count, so this never leaks a masked self-match."""
        exclude = exclude or set()
        idxs = [i for i in self._exact.get(normalize(query), []) if i not in exclude]
        return {self.anchor_concept[i] for i in idxs}


class Signal(ABC):
    name: str

    def __init__(self, index: AnchorIndex):
        self.index = index

    @abstractmethod
    def _anchor_scores(self, query: str) -> np.ndarray:
        """Per-anchor similarity in [0, 1], aligned to index.anchors."""

    def rank(self, query: str, exclude: set[int] | None = None) -> dict[str, float]:
        """Per-concept score = max over its (non-excluded) anchors. Empty if all masked."""
        scores = self._anchor_scores(query)
        exclude = exclude or set()
        out: dict[str, float] = {}
        for cid, idxs in self.index.concept_anchor_idx.items():
            live = [i for i in idxs if i not in exclude]
            if live:
                out[cid] = float(scores[live].max())
        return out


class CharNgramSignal(Signal):
    name = "charngram"

    def __init__(self, index: AnchorIndex, ngram_range: tuple[int, int] = (2, 4)):
        super().__init__(index)
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=ngram_range)
        self.matrix = self.vec.fit_transform(charstream(a) for a in index.anchors)
        # rows are L2-normalized by TfidfVectorizer(norm='l2') default => cosine = dot.

    def _anchor_scores(self, query: str) -> np.ndarray:
        q = self.vec.transform([charstream(query)])
        sims = (self.matrix @ q.T).toarray().ravel()  # cosine, anchors already unit-norm
        return sims


class FuzzySignal(Signal):
    name = "fuzzy"

    def __init__(self, index: AnchorIndex):
        super().__init__(index)
        self._norm_anchors = [normalize(a) for a in index.anchors]

    def _anchor_scores(self, query: str) -> np.ndarray:
        q = normalize(query)
        # blend token-set (order/word robust) with WRatio (partial/typo robust)
        return np.array(
            [
                max(fuzz.token_set_ratio(q, a), fuzz.WRatio(q, a)) / 100.0
                for a in self._norm_anchors
            ]
        )


if __name__ == "__main__":
    from .concepts import build_concepts

    idx = AnchorIndex(build_concepts())
    signals = [CharNgramSignal(idx), FuzzySignal(idx)]
    for q in ["chckt_strt", "BeginCheckout", "add_itm_to_crt", "sssn_strt", "prdct_dtl_vw"]:
        excl = idx.exclude_for(q)
        print(f"\nquery={q!r}  (leave-one-out: masking {len(excl)} anchor)")
        for sig in signals:
            ranked = sorted(sig.rank(q, excl).items(), key=lambda kv: -kv[1])[:3]
            top = ", ".join(f"{c}={s:.2f}" for c, s in ranked)
            print(f"  {sig.name:10s} {top}")
