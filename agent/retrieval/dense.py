"""Dense semantic signal — local bge-small embeddings over concept *profiles*.

Where the lexical signals see *characters*, dense sees *meaning*: it scores a query
name against each concept's profile text (label + human description), so
`product_detail_view` beats the other `*_view` concepts because "User opens a product
detail page" is semantically nearer than "User views the home screen" — a distinction
char-ngrams and edit distance cannot make (they all end in "view").

Design choices that keep it honest and cheap:
  * Embeds ONLY `label + description` — never the aliases — so leave-one-out is
    inherent: the query's own surface string is nowhere in the target, no masking
    needed, no leakage.
  * Local ONNX model (`BAAI/bge-small-en-v1.5` via fastembed) — no torch, no API, no
    cost, deterministic. Pinned model + revision => same corpus, same vectors.
  * Embeddings computed once at build; query is a single embed at resolve time.
"""

from __future__ import annotations

import numpy as np

from .concepts import Concept
from .embedder import MODEL_NAME, get_embedder
from .lexical import AnchorIndex, Signal
from .normalize import normalize


def _l2(m: np.ndarray) -> np.ndarray:
    return m / np.clip(np.linalg.norm(m, axis=-1, keepdims=True), 1e-12, None)


class DenseSignal(Signal):
    name = "dense"

    def __init__(self, index: AnchorIndex, model_name: str = MODEL_NAME):
        super().__init__(index)
        self.model = get_embedder(model_name)
        self.concept_ids = [c.concept_id for c in index.concepts]
        profiles = [self._profile(c) for c in index.concepts]
        self.matrix = _l2(np.array(list(self.model.embed(profiles))))  # (n_concepts, d)
        self._qcache: dict[str, np.ndarray] = {}  # query embeddings repeat across variants

    @staticmethod
    def _profile(c: Concept) -> str:
        # bge retrieval convention: a short passage. Label + description is enough.
        return f"{c.concept_id.replace('_', ' ')}. {c.description}"

    def _embed_query(self, query: str) -> np.ndarray:
        q = normalize(query) or query.lower()
        if q not in self._qcache:
            self._qcache[q] = _l2(np.array(list(self.model.embed([q]))[0]))
        return self._qcache[q]

    def rank(self, query: str, exclude: set[int] | None = None) -> dict[str, float]:
        # exclude is ignored: profiles contain no alias anchors, so LOO is inherent.
        sims = self.matrix @ self._embed_query(query)  # cosine, both unit-norm
        return {cid: float(max(0.0, s)) for cid, s in zip(self.concept_ids, sims)}

    def _anchor_scores(self, query: str):  # not used; dense scores at concept level
        raise NotImplementedError


if __name__ == "__main__":
    from .concepts import build_concepts

    sig = DenseSignal(AnchorIndex(build_concepts()))
    for q in ["prdct_dtl_vw", "chckt_strt", "sssn_strt", "bnr_clk", "zzz_garbage"]:
        top = sorted(sig.rank(q).items(), key=lambda kv: -kv[1])[:3]
        print(f"  {q:16s} -> " + ", ".join(f"{c}={s:.2f}" for c, s in top))
