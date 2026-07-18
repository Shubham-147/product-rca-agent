"""System-A-specific validation layered on shared report guardrails."""
from __future__ import annotations
from src.guardrails import GuardrailError,validate_report
from src.retrieval.schemas import EventResolution
from src.schemas import AnalysisRequest,RCAReport

def validate_system_a_output(report:RCAReport,request:AnalysisRequest,*,query_ids:set[str],chunk_ids:set[str],
                             resolutions:dict[str,EventResolution],max_hypotheses:int,run_id:str)->RCAReport:
    if report.instance_id!=request.instance_id or report.symptom!=request.symptom:raise GuardrailError("report request fields do not match")
    if report.run_metadata.run_id!=run_id or report.run_metadata.system_name!="system_a":raise GuardrailError("invalid System A run metadata")
    if any(not h.evidence for h in report.hypotheses):raise GuardrailError("each hypothesis requires numerical evidence")
    known=set(resolutions)
    for hypothesis in report.hypotheses:
        unknown=set(hypothesis.resolved_events)-known
        if unknown:raise GuardrailError(f"unknown canonical events: {sorted(unknown)}")
    return validate_report(report,query_ids=query_ids,source_chunk_ids=chunk_ids,
                           event_resolutions=resolutions,max_hypotheses=max_hypotheses)
