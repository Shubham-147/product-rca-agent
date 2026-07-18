"""Bounded prompt context containing textual chunks and aggregate evidence only."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel,ConfigDict,Field
from src.retrieval.schemas import Chunk
from .errors import GuardrailError

class PromptContext(BaseModel):
    model_config=ConfigDict(extra="forbid")
    chunks:list[Chunk]=Field(default_factory=list)
    aggregate_results:list[Any]=Field(default_factory=list)

def build_prompt_context(chunks:list[Chunk],results:list[Any],*,max_chunks:int,max_chars:int)->PromptContext:
    unique=[];seen=set()
    for c in chunks:
        if c.chunk_id in seen:continue
        seen.add(c.chunk_id)
        if len(c.text)>max_chars:raise GuardrailError("retrieval chunk exceeds prompt character limit")
        unique.append(c)
    if len(unique)>max_chunks:raise GuardrailError("retrieval chunk count exceeds prompt limit")
    for result in results:
        for row in result.rows:
            if any(isinstance(v,(list,tuple,set)) and len(v)>20 for v in row.values()):
                raise GuardrailError("complete user/cohort lists are forbidden in prompts")
            if {"user_id","session_id","event_ts"}.issubset(row):
                raise GuardrailError("raw event rows are forbidden in prompts")
    return PromptContext(chunks=unique,aggregate_results=_dedupe_results(results))

def _dedupe_results(results):
    out=[];seen=set()
    for result in results:
        if result.query_id not in seen:seen.add(result.query_id);out.append(result)
    return out
