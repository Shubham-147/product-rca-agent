"""Runtime dependencies and guarded node execution helpers."""
from __future__ import annotations
import time
from dataclasses import dataclass,field
from typing import Any,Protocol
from pydantic import BaseModel
from src.analytics import DeterministicAnalytics
from src.config import AppSettings
from src.database import DuckDBManager,QueryResult
from src.guardrails import SafeAuditLogger,SystemCGraphGuard
from src.retrieval import CanonicalEventResolver,HybridRetriever

class StructuredModel(Protocol):
    def complete(self,task:str,payload:dict[str,Any],output_type:type[BaseModel])->Any:...

@dataclass
class SystemCDependencies:
    analytics:DeterministicAnalytics
    retriever:HybridRetriever
    resolver:CanonicalEventResolver
    manager:DuckDBManager
    model:StructuredModel
    guard:SystemCGraphGuard
    logger:SafeAuditLogger
    settings:AppSettings
    instance_id:str
    run_id:str
    query_cache:dict[str,QueryResult]=field(default_factory=dict)
    known_query_results:dict[str,QueryResult]=field(default_factory=dict)
    known_chunk_ids:set[str]=field(default_factory=set)

class Node:
    name="node"
    def __init__(self,deps:SystemCDependencies):self.deps=deps
    def __call__(self,state):
        started=time.perf_counter()
        try:
            result,cached=self.deps.guard.execute_node(self.name,_StateFingerprint.from_state(state),lambda:self.run(state),cacheable=False)
            duration=(time.perf_counter()-started)*1000
            self.deps.logger.log(tool=f"system_c_node:{self.name}",duration_ms=duration,cache_status="hit" if cached else "miss")
            result["node_execution_count"]=self.deps.guard.nodes
            trace=list(result.get("trace",state.get("trace",[])));trace.append({"node":self.name,"duration_ms":duration,"cache":"hit" if cached else "miss"})
            result["trace"]=trace;return result
        except Exception as exc:
            self.deps.logger.log(tool=f"system_c_node:{self.name}",duration_ms=(time.perf_counter()-started)*1000,error=exc,cache_status="miss")
            raise
    def run(self,state):raise NotImplementedError

class _StateFingerprint(BaseModel):
    instance_id:str;hypothesis_id:str|None=None;revision:int=0
    @classmethod
    def from_state(cls,state):
        request=state.get("request");hyp=state.get("current_hypothesis")
        return cls(instance_id=request.instance_id if request else "pending",hypothesis_id=hyp.hypothesis_id if hyp else None,revision=state.get("revision_count",0))

def remember(deps,result):deps.known_query_results[result.query_id]=result;return result
