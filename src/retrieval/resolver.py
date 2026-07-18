"""Conservative canonical-event resolution and deterministic alias maps."""
from __future__ import annotations
import json
from collections import defaultdict
from .hybrid import HybridRetriever
from .schemas import *

class CanonicalEventResolver:
    def __init__(self,records:list[TaxonomyRecord],retriever:HybridRetriever,taxonomy_version="unknown"):
        self.records={r.canonical_event:r for r in records};self.retriever=retriever;self.version=taxonomy_version
        self.aliases={a:r.canonical_event for r in records for a in [r.canonical_event,*r.aliases]}
        self.aliases_lower={a.lower():c for a,c in self.aliases.items()}
    def resolve(self,concept,raw_event_name=None,screen=None,funnel_name=None,top_k=5):
        raw=(raw_event_name or "").strip()
        if raw and raw.lower() in self.aliases_lower:
            canonical=self.aliases_lower[raw.lower()];r=self.records[canonical]
            candidate=self._candidate(r,.99,"exact_alias",[raw],[])
            return EventResolution(concept=concept,candidates=[candidate],resolved=True,selected=candidate)
        query=" ".join(x for x in [concept,raw,screen or "",funnel_name or ""] if x)
        hits=self.retriever.retrieve(query,RetrievalMode.EVENT_RESOLUTION,top_k=20)
        grouped=defaultdict(list)
        for hit in hits: grouped[hit.chunk.metadata.get("canonical_event","")].append(hit)
        candidates=[]
        for canonical,items in grouped.items():
            if canonical not in self.records:continue
            r=self.records[canonical];best=items[0];score=float(best.rerank_score or 0)
            # Bound arbitrary reranker scales and require lexical/semantic agreement.
            confidence=max(0,min(.84,.5+.2*score+.12*(best.sparse_rank is not None)+.08*(best.dense_rank is not None)))
            if screen and r.screen and screen.lower()==r.screen.lower():confidence=min(.9,confidence+.08)
            if r.is_active:confidence=min(.9,confidence+.03)
            warnings=[] if confidence>=.85 else (["medium-confidence mapping; verify before use"] if confidence>=.65 else ["low-confidence event; unresolved"])
            candidates.append(self._candidate(r,confidence,"hybrid",[],[x.chunk.chunk_id for x in items],warnings))
        candidates.sort(key=lambda c:(-c.confidence,c.canonical_event));candidates=candidates[:top_k]
        selected=candidates[0] if candidates and candidates[0].confidence>=.65 else None
        return EventResolution(concept=concept,candidates=candidates,resolved=selected is not None,selected=selected,
            warnings=[] if selected else ["No candidate met the 0.65 confidence threshold."])
    def _candidate(self,r,confidence,method,matched,evidence,warnings=None):
        return CanonicalCandidate(canonical_event=r.canonical_event,aliases=list(dict.fromkeys([r.canonical_event,*r.aliases])),
            matched_aliases=matched,screen=r.screen,confidence=confidence,resolution_method=method,
            evidence_chunk_ids=evidence,warnings=warnings or [])
    def alias_mappings(self)->list[AliasMapping]:
        out=[]
        for r in sorted(self.records.values(),key=lambda x:x.canonical_event):
            for alias in sorted(set([r.canonical_event,*r.aliases])):
                out.append(AliasMapping(raw_event_name=alias,canonical_event=r.canonical_event,is_resolved=True,
                    funnel_step=r.funnel_step,is_expected_dropoff=r.is_expected_dropoff,taxonomy_version=self.version))
        return out
