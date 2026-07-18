"""Explicit construction entry point for the shared retrieval pipeline."""
from __future__ import annotations
from src.config import AppSettings,get_settings
from .hybrid import HybridRetriever
from .indexes import ChromaDenseIndex,Embedder
from .reranker import CrossEncoderReranker
from .schemas import Chunk

def build_hybrid_retriever(chunks:list[Chunk],settings:AppSettings|None=None,*,embedder:Embedder|None=None,reranker=None,index_dense=True):
    cfg=settings or get_settings()
    dense=ChromaDenseIndex(cfg.chroma_persist_path,cfg.embedding_model,embedder)
    service=HybridRetriever(chunks,dense,reranker or CrossEncoderReranker(cfg.reranker_model),cfg.rrf_constant,cfg.max_chunks_per_parent)
    if index_dense: service.build_dense(cfg.index_batch_size)
    return service
