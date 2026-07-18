"""Daily, credential-free records of logical payloads sent to provider models."""
from __future__ import annotations

import json
import threading
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

_LOCK=threading.Lock()
_SECRET_KEYS=("api_key","authorization","token","secret","password")

def write_daily_openai_payload(*,system_name:str,stage:str,model:str,payload:Any,
                               log_root:Path=Path("log"))->Path:
    """Append one JSON record to log/YYYY-MM-DD.txt immediately before a model call."""
    now=datetime.now(timezone.utc)
    target=log_root/f"{now.astimezone().date().isoformat()}.txt"
    record={"timestamp":now.isoformat(),"system_name":system_name,"stage":stage,
      "model":model,"payload":_redact_secret_fields(payload)}
    with _LOCK:
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open("a",encoding="utf-8") as handle:
            handle.write(json.dumps(record,ensure_ascii=False,default=str)+"\n")
    return target

def _redact_secret_fields(value:Any)->Any:
    if isinstance(value,dict):
        return {key:("[REDACTED]" if any(term in str(key).lower() for term in _SECRET_KEYS)
          else _redact_secret_fields(child)) for key,child in value.items()}
    if isinstance(value,(list,tuple)):return [_redact_secret_fields(child) for child in value]
    return value
