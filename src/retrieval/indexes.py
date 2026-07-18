"""Lazy dense and sparse indexes over the identical chunk set."""
from __future__ import annotations
import json, logging, math, re
from collections import Counter
from pathlib import Path
from typing import Protocol
from .schemas import Chunk

def tokenize(text:str)->list[str]: return re.findall(r"[A-Za-z0-9_]+",text.lower())

class Embedder(Protocol):
    def encode(self,texts:list[str])->list[list[float]]: ...

class SentenceTransformerEmbedder:
    def __init__(self,model_name:str): self.model_name=model_name; self._model=None
    def encode(self,texts):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            try:self._model=SentenceTransformer(self.model_name,device="cpu",local_files_only=True)
            except Exception:self._model=SentenceTransformer(self.model_name,device="cpu")
        return self._model.encode(texts,normalize_embeddings=True).tolist()

class BM25Index:
    def __init__(self): self.chunks=[];self.tf=[];self.df=Counter();self.avg=0
    def build(self,chunks:list[Chunk]):
        self.chunks=list(chunks);self.tf=[];self.df=Counter();lengths=[]
        for c in chunks:
            toks=tokenize(c.text); counts=Counter(toks);self.tf.append(counts);lengths.append(len(toks));self.df.update(counts)
        self.avg=sum(lengths)/len(lengths) if lengths else 1
    def search(self,query:str,k=20,allowed_types:set[str]|None=None):
        q=tokenize(query);n=max(len(self.chunks),1);scores=[]
        for i,(c,tf) in enumerate(zip(self.chunks,self.tf)):
            if allowed_types and c.document_type not in allowed_types: continue
            dl=sum(tf.values());score=0.0
            for term in q:
                f=tf[term];df=self.df[term]
                if f: score+=math.log(1+(n-df+0.5)/(df+0.5))*f*2.2/(f+1.2*(.25+.75*dl/self.avg))
            if score>0:scores.append((c,score))
        return sorted(scores,key=lambda x:(-x[1],x[0].chunk_id))[:k]

class ChromaDenseIndex:
    def __init__(self,path:Path,model_name:str,embedder:Embedder|None=None,collection="product_rca"):
        self.path=path;self.model_name=model_name;self.embedder=embedder;self.collection_name=collection;self._collection=None
    def _init(self):
        if self._collection is None:
            import chromadb
            from chromadb.config import Settings
            # Product telemetry is disabled below. Chroma 0.6.x nevertheless
            # invokes its telemetry adapter, which emits compatibility errors
            # with newer PostHog clients before their disabled flag is checked.
            logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)
            self.path.mkdir(parents=True,exist_ok=True)
            self._collection=chromadb.PersistentClient(
                path=str(self.path), settings=Settings(anonymized_telemetry=False)
            ).get_or_create_collection(self.collection_name)
            self.embedder=self.embedder or SentenceTransformerEmbedder(self.model_name)
    def index(self,chunks:list[Chunk],batch_size=64):
        self._init(); existing=self._collection.get(include=["metadatas"])
        current=set(existing["ids"]); wanted={c.chunk_id for c in chunks}
        hashes={cid:(meta or {}).get("content_hash") for cid,meta in zip(existing["ids"],existing["metadatas"])}
        stale=list(current-wanted)
        if stale:self._collection.delete(ids=stale)
        changed=[c for c in chunks if hashes.get(c.chunk_id)!=c.content_hash]
        for start in range(0,len(changed),batch_size):
            batch=changed[start:start+batch_size];emb=self.embedder.encode([c.text for c in batch])
            metas=[]
            for c in batch:
                m={"document_type":c.document_type,"document_id":c.document_id,"content_hash":c.content_hash,
                   "parent_chunk_id":c.parent_chunk_id or ""}
                m.update({k:(json.dumps(v) if isinstance(v,(list,dict)) else v) for k,v in c.metadata.items() if v is not None})
                metas.append(m)
            self._collection.upsert(ids=[c.chunk_id for c in batch],documents=[c.text for c in batch],metadatas=metas,embeddings=emb)
    def search(self,query:str,k=20,allowed_types:set[str]|None=None)->list[tuple[str,float]]:
        self._init();where={"document_type":{"$in":sorted(allowed_types)}} if allowed_types else None
        result=self._collection.query(query_embeddings=self.embedder.encode([query]),n_results=k,where=where,include=["distances"])
        return [(cid,1/(1+dist)) for cid,dist in zip(result["ids"][0],result["distances"][0])]

def reciprocal_rank_fusion(dense_ids:list[str],sparse_ids:list[str],constant=60,dense_weight=1.0,sparse_weight=1.0):
    scores={}
    for rank,cid in enumerate(dense_ids,1):scores[cid]=scores.get(cid,0)+dense_weight/(constant+rank)
    for rank,cid in enumerate(sparse_ids,1):scores[cid]=scores.get(cid,0)+sparse_weight/(constant+rank)
    return sorted(scores.items(),key=lambda x:(-x[1],x[0]))
