"""Tool and graph execution budgets with caching and cycle protection."""
from __future__ import annotations
import hashlib,json
from concurrent.futures import ThreadPoolExecutor,TimeoutError
from typing import Any,Callable,Literal
from pydantic import BaseModel
from .errors import GuardrailError

def _fingerprint(name,args)->str:
    payload=args.model_dump(mode="json") if isinstance(args,BaseModel) else args
    return hashlib.sha256(json.dumps([name,payload],sort_keys=True,default=str).encode()).hexdigest()
def _timed(fn,timeout):
    pool=ThreadPoolExecutor(max_workers=1);future=pool.submit(fn)
    try:return future.result(timeout=timeout)
    except TimeoutError as exc:future.cancel();raise GuardrailError("guarded execution timed out") from exc
    finally:pool.shutdown(wait=False,cancel_futures=True)

class SystemBToolGuard:
    def __init__(self,total=15,retrieval=4,analytical=10,timeout_seconds=30):
        if total>15 or retrieval>4 or analytical>10:raise GuardrailError("System B budget exceeds hard maximum")
        self.maximums={"retrieval":retrieval,"analytical":analytical};self.total_max=total;self.timeout=timeout_seconds
        self.counts={"retrieval":0,"analytical":0};self.total=0;self.cache={}
    def execute(self,tool:str,kind:Literal["retrieval","analytical"],args:BaseModel,fn:Callable[[],Any]):
        if not isinstance(args,BaseModel):raise GuardrailError("tool arguments must be typed Pydantic models")
        key=_fingerprint(tool,args)
        if key in self.cache:return self.cache[key],True
        if self.total>=self.total_max or self.counts[kind]>=self.maximums[kind]:raise GuardrailError("System B tool-call budget exceeded")
        self.total+=1;self.counts[kind]+=1;result=_timed(fn,self.timeout);self.cache[key]=result
        return result,False

class SystemCGraphGuard:
    def __init__(self,max_revisions=2,max_node_executions=30,timeout_seconds=60):
        if max_revisions>2:raise GuardrailError("System C revisions cannot exceed two")
        self.max_revisions=max_revisions;self.max_nodes=max_node_executions;self.timeout=timeout_seconds
        self.revisions=0;self.nodes=0;self.hypothesis_fingerprints=set();self.revision_counts={};self.cache={}
    def register_revision(self,hypothesis:BaseModel|dict,scope:str|None=None):
        key=_fingerprint(f"hypothesis:{scope or 'global'}",hypothesis)
        if key in self.hypothesis_fingerprints:raise GuardrailError("identical hypothesis revision rejected")
        count=self.revision_counts.get(scope or "__global__",0)
        if count>=self.max_revisions:raise GuardrailError("System C revision limit exceeded")
        self.hypothesis_fingerprints.add(key);self.revisions+=1;self.revision_counts[scope or "__global__"]=count+1
    def execute_node(self,node:str,args:BaseModel,fn:Callable[[],Any],cacheable=True):
        if not isinstance(args,BaseModel):raise GuardrailError("node arguments must be typed Pydantic models")
        key=_fingerprint(node,args)
        if cacheable and key in self.cache:return self.cache[key],True
        if self.nodes>=self.max_nodes:raise GuardrailError("System C node execution limit exceeded")
        self.nodes+=1;result=_timed(fn,self.timeout)
        if cacheable:self.cache[key]=result
        return result,False
