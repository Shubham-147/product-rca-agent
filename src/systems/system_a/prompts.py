"""Single analytical prompt for Vanilla RAG System A."""
from __future__ import annotations
import json
from src.guardrails import PromptContext
from src.schemas import AnalysisRequest,RCAReport,RunMetadata
from .evidence_pack import FixedEvidencePack

SYSTEM_INSTRUCTIONS="""You are System A, a non-agentic product root-cause analyst.
Return exactly one RCAReport matching the supplied JSON schema. Distinguish a symptom from a mechanism.
Every hypothesis must define an explicit cohort, use only supplied aggregate evidence, cite query_id for every number,
cite source_chunk_ids for every product fact, name unresolved confounders, avoid causal certainty when alternatives remain,
and include limitations. Never invent fields, events, metrics, SQL results, users, or product rules.
Do not request tools, further analysis, revised evidence, or hidden ground truth."""

def build_prompt(request:AnalysisRequest,pack:FixedEvidencePack,context:PromptContext,metadata:RunMetadata)->str:
    evidence=[{"name":item.name,**item.result.model_dump(mode="json")} for item in pack.items]
    chunks=[{"chunk_id":c.chunk_id,"document_type":c.document_type,"text":c.text,"metadata":c.metadata} for c in context.chunks]
    payload={"request":request.model_dump(mode="json"),"required_run_metadata":metadata.model_dump(mode="json"),
             "aggregate_evidence":evidence,"product_context":chunks,"output_json_schema":RCAReport.model_json_schema()}
    return SYSTEM_INSTRUCTIONS+"\n\nINPUT:\n"+json.dumps(payload,default=str)

def build_schema_repair_prompt(original_prompt:str,error:str)->str:
    return original_prompt+"\n\nSCHEMA REPAIR ONLY. The prior response failed validation: "+error+". Return corrected JSON without new analysis."
