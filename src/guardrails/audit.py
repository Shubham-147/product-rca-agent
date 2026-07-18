"""Redacted operational audit records; never chain-of-thought or raw datasets."""
from __future__ import annotations
import logging,re
from typing import Any
_SECRET=re.compile(r"(api[_-]?key|authorization|token|secret|password)",re.I)
_HIDDEN=re.compile(r"manifest|ground_truth|planted_fault|fault_manifest|scorer|labels|answers",re.I)

class SafeAuditLogger:
    def __init__(self,logger=None):self.logger=logger or logging.getLogger("product_rca.audit")
    def log(self,*,sql=None,parameters=None,query_id=None,tool=None,arguments=None,result_size=None,
            result_summary=None,duration_ms=None,error=None,cache_status=None):
        record={"sql":sql,"parameters":parameters,"query_id":query_id,"tool":tool,"arguments":arguments,
                "result_size":result_size,"result_summary":result_summary,"duration_ms":duration_ms,
                "error":str(error) if error else None,"cache_status":cache_status}
        safe=_redact(record);self.logger.info("guarded_operation %s",safe);return safe
def _redact(value:Any):
    if isinstance(value,dict):return {k:("[REDACTED]" if _SECRET.search(k) else _redact(v)) for k,v in value.items()}
    if isinstance(value,(list,tuple)):
        if len(value)>20:return f"[REDACTED COLLECTION size={len(value)}]"
        return [_redact(v) for v in value]
    if isinstance(value,str) and (_SECRET.search(value) or _HIDDEN.search(value)):return "[REDACTED]"
    return value
