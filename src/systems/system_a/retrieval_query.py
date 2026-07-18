"""Deterministic retrieval queries for System A."""
from __future__ import annotations
from src.retrieval import HybridRetriever,RetrievalMode,Chunk
from src.schemas import AnalysisRequest
from .evidence_pack import FUNNEL_STEPS

def build_retrieval_queries(request:AnalysisRequest)->list[tuple[str,RetrievalMode]]:
    screen=request.suspected_screen or ""
    return [
      (f"{request.symptom} {screen} intended behavior acceptance rules exceptions expected dropoff",RetrievalMode.PRODUCT_INTENT),
      (f"{' '.join(FUNNEL_STEPS)} optional steps alternative paths",RetrievalMode.PRODUCT_INTENT),
      ("checkout_completion_rate crash_rate checkout_crash_rate latency_p50 latency_p95 numerator denominator limitations",RetrievalMode.METRIC_DEFINITION),
      (f"{request.symptom} {screen}",RetrievalMode.HISTORICAL_TICKET),
    ]

def retrieve_context(retriever:HybridRetriever,request:AnalysisRequest,maximum_chunks:int)->list[Chunk]:
    chunks=[];seen=set()
    for query,mode in build_retrieval_queries(request):
        for hit in retriever.retrieve(query,mode,top_k=maximum_chunks):
            if hit.chunk.chunk_id not in seen:seen.add(hit.chunk.chunk_id);chunks.append(hit.chunk)
            if len(chunks)>=maximum_chunks:return chunks
    return chunks
