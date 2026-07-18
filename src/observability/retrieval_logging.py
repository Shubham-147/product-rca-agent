"""Safe, bounded logging of agent-visible retrieval context before LLM calls."""
from __future__ import annotations

import re
from typing import Any,Iterable

_SENSITIVE=re.compile(r"api[_-]?key|authorization|bearer\s+|token|secret|password|ground_truth|manifest|planted_fault",re.I)
_PREVIEW_CHARACTERS=300

def retrieval_chunk_descriptors(chunks:Iterable[Any])->list[dict[str,Any]]:
    descriptors=[]
    for item in chunks:
        chunk=item.get("chunk",item) if isinstance(item,dict) else item
        if isinstance(chunk,dict):
            chunk_id=chunk.get("chunk_id");document_type=chunk.get("document_type");text=str(chunk.get("text", ""))
        else:
            chunk_id=getattr(chunk,"chunk_id",None);document_type=getattr(chunk,"document_type",None);text=str(getattr(chunk,"text", ""))
        normalized=" ".join(text.split())
        preview="[REDACTED]" if _SENSITIVE.search(normalized) else normalized[:_PREVIEW_CHARACTERS]
        descriptors.append({"chunk_id":chunk_id,"document_type":document_type,
          "character_count":len(text),"preview":preview})
    return descriptors

def log_retrieved_chunks(audit_logger,*,system_name:str,stage:str,chunks:Iterable[Any])->list[dict[str,Any]]:
    descriptors=retrieval_chunk_descriptors(chunks)
    audit_logger.log(tool="pre_llm_retrieval_context",arguments={"system_name":system_name,
      "stage":stage,"chunks":descriptors},result_size=len(descriptors),
      result_summary=f"{len(descriptors)} agent-visible retrieval chunks prepared for the LLM")
    return descriptors
