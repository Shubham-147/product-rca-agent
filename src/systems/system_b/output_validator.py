"""Stored-result-aware validation for System B reports."""
from __future__ import annotations

import math
from numbers import Number

from src.config import AppSettings
from src.guardrails import GuardrailError, validate_report
from src.schemas import AnalysisRequest, RCAReport

from .dependencies import SystemBDependencies


def validate_system_b_output(report:RCAReport,request:AnalysisRequest,deps:SystemBDependencies,
                             settings:AppSettings)->RCAReport:
    if report.instance_id!=request.instance_id or report.symptom!=request.symptom:
        raise GuardrailError("report request fields do not match")
    metadata=report.run_metadata
    if metadata.run_id!=deps.run_id or metadata.system_name!="system_b":
        raise GuardrailError("invalid System B run metadata")
    report=validate_report(report,query_ids=set(deps.query_results),source_chunk_ids=deps.source_chunks,
        event_resolutions=deps.event_resolutions,max_hypotheses=min(settings.max_hypotheses,5))
    evidence_errors=draft_evidence_errors(report,deps)
    if evidence_errors:raise GuardrailError(evidence_errors[0])
    budget_exhausted=deps.guardrail_service.total>=deps.guardrail_service.total_max
    qualified=any(len(h.evidence)>=2 and any(e.sample_size>=settings.minimum_segment_size for e in h.evidence)
                  and h.confounders for h in report.hypotheses)
    if report.hypotheses and not (qualified or budget_exhausted):
        raise GuardrailError("System B exit conditions were not met")
    return report


def draft_evidence_errors(report:RCAReport,deps:SystemBDependencies)->list[str]:
    """Return safe, actionable mismatches between draft evidence and stored aggregates."""
    errors=[]
    for hypothesis in report.hypotheses:
        for evidence in hypothesis.evidence:
            result=deps.query_results.get(evidence.query_id)
            if result is None:
                errors.append(f"evidence {evidence.evidence_id} uses an unknown query_id")
                continue
            values=_numeric_values(result.rows)
            if not _contains(values,evidence.observed_value):
                errors.append(f"evidence {evidence.evidence_id} observed_value does not match its stored query result")
            if evidence.sample_size not in {int(v) for v in values if float(v).is_integer()}:
                errors.append(f"evidence {evidence.evidence_id} sample_size does not match its stored query result")
    return errors


def _numeric_values(rows):
    values=[]
    def visit(value):
        if isinstance(value,bool):return
        if isinstance(value,Number):values.append(float(value))
        elif isinstance(value,dict):
            for child in value.values():visit(child)
        elif isinstance(value,(list,tuple)):
            for child in value:visit(child)
    visit(rows);return values


def _contains(values,target):return any(math.isclose(value,float(target),rel_tol=1e-9,abs_tol=1e-9) for value in values)
