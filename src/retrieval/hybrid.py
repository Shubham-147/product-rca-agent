"""Mode-aware hybrid retrieval with RRF, reranking, and parent diversity."""
from __future__ import annotations
from .indexes import BM25Index,ChromaDenseIndex,reciprocal_rank_fusion
from .reranker import CrossEncoderReranker,LexicalFallbackReranker
from .schemas import *

MODE_TYPES={
 RetrievalMode.EVENT_RESOLUTION:{"taxonomy"},
 RetrievalMode.PRODUCT_INTENT:{"prd","funnel"},
 RetrievalMode.HISTORICAL_TICKET:{"ticket"},
 RetrievalMode.METRIC_DEFINITION:{"metric"},
}
MODE_WEIGHTS={RetrievalMode.EVENT_RESOLUTION:(.7,1.5),RetrievalMode.PRODUCT_INTENT:(1.4,.8),
 RetrievalMode.HISTORICAL_TICKET:(1,1),RetrievalMode.METRIC_DEFINITION:(.8,1.2)}

class HybridRetriever:
    def __init__(self,chunks,dense_index,reranker=None,rrf_constant=60,max_per_parent=2):
        self.chunks={c.chunk_id:c for c in chunks};self.sparse=BM25Index();self.sparse.build(chunks)
        self.dense=dense_index;self.reranker=reranker or LexicalFallbackReranker();self.rrf_constant=rrf_constant;self.max_per_parent=max_per_parent
    def build_dense(self,batch_size=64):self.dense.index(list(self.chunks.values()),batch_size)
    def retrieve(self,query,mode,top_k=5,metadata_filters=None,allow_parent_duplicates=False):
        mode=RetrievalMode(mode);types=MODE_TYPES[mode];dw,sw=MODE_WEIGHTS[mode]
        sparse=self.sparse.search(query,20,types);dense=self.dense.search(query,20,types)
        fused=reciprocal_rank_fusion([x[0] for x in dense],[x[0].chunk_id for x in sparse],self.rrf_constant,dw,sw)
        candidates=[]
        sparse_rank={c.chunk_id:i for i,(c,_) in enumerate(sparse,1)};dense_rank={x[0]:i for i,x in enumerate(dense,1)}
        for cid,score in fused:
            c=self.chunks.get(cid)
            if not c or (metadata_filters and any(c.metadata.get(k)!=v for k,v in metadata_filters.items())):continue
            candidates.append(RetrievedChunk(chunk=c,dense_rank=dense_rank.get(cid),sparse_rank=sparse_rank.get(cid),fused_score=score))
            if len(candidates)>=20:break
        if candidates:
            scores=self.reranker.score(query,[x.chunk.text for x in candidates])
            for item,score in zip(candidates,scores):item.rerank_score=score
            candidates.sort(key=lambda x:(-(x.rerank_score or 0),-x.fused_score,x.chunk.chunk_id))
        out=[];parents={}
        for item in candidates:
            parent=item.chunk.parent_chunk_id
            if parent and not allow_parent_duplicates and parents.get(parent,0)>=self.max_per_parent:continue
            out.append(item);parents[parent]=parents.get(parent,0)+1
            if len(out)>=top_k:break
        return out
