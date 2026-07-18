"""Evidence and final-report traceability validation."""
from __future__ import annotations
import re
from pydantic import BaseModel,ConfigDict,Field
from src.guardrails.cohorts import compile_cohort
from src.schemas import RCAReport
from src.retrieval.schemas import EventResolution
from .errors import GuardrailError

class ProductFact(BaseModel):
    model_config=ConfigDict(extra="forbid")
    claim:str
    source_chunk_id:str=Field(min_length=1)

def validate_report(report:RCAReport,*,query_ids:set[str],source_chunk_ids:set[str],
                    event_resolutions:dict[str,EventResolution]|None=None,max_hypotheses=5)->RCAReport:
    if len(report.hypotheses)>max_hypotheses:raise GuardrailError("too many hypotheses")
    for hypothesis in report.hypotheses:
        compile_cohort(report.instance_id,hypothesis.affected_cohort)
        if not hypothesis.limitations:raise GuardrailError("every hypothesis must include limitations")
        if _repeats_symptom(hypothesis.mechanism,report.symptom):raise GuardrailError("mechanism only repeats the symptom")
        for evidence in hypothesis.evidence:
            if not evidence.query_id or evidence.query_id not in query_ids:raise GuardrailError("evidence query_id is missing or unknown")
            if not evidence.metric_name or evidence.sample_size is None or evidence.observed_value is None:raise GuardrailError("numerical evidence is incomplete")
            missing=set(evidence.source_chunk_ids)-source_chunk_ids
            if missing:raise GuardrailError(f"unknown source chunk IDs: {sorted(missing)}")
        if event_resolutions is not None:
            for event in hypothesis.resolved_events:
                resolution=event_resolutions.get(event)
                if not resolution or not resolution.resolved or not resolution.selected or resolution.selected.confidence<.65:
                    raise GuardrailError("unresolved event presented as certain")
    return report

def validate_product_facts(facts:list[ProductFact],source_chunk_ids:set[str])->None:
    if any(f.source_chunk_id not in source_chunk_ids for f in facts):raise GuardrailError("product fact lacks a valid source chunk ID")

def _repeats_symptom(mechanism,symptom):
    words=lambda x:set(re.findall(r"[a-z0-9_]+",x.lower()))
    a,b=words(mechanism),words(symptom)
    return bool(a and b and (a==b or len(a&b)/max(len(a|b),1)>.9))
