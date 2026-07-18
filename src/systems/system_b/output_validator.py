"""Stored-result-aware validation for System B reports."""
from __future__ import annotations

import math
from numbers import Number

from src.config import AppSettings
from src.guardrails import GuardrailError, compile_cohort
from src.schemas import AnalysisRequest, RCAReport

from .dependencies import SystemBDependencies


def validate_system_b_output(report:RCAReport,request:AnalysisRequest,deps:SystemBDependencies,
                             settings:AppSettings)->RCAReport:
    if report.instance_id!=request.instance_id or report.symptom!=request.symptom:
        raise GuardrailError("report request fields do not match")
    metadata=report.run_metadata
    if metadata.run_id!=deps.run_id or metadata.system_name!="system_b":
        raise GuardrailError("invalid System B run metadata")
    sanitized=[]
    for hypothesis in report.hypotheses[:min(settings.max_hypotheses,5)]:
        # Cohort compilation is an instance-isolation boundary and remains strict.
        compile_cohort(request.instance_id,hypothesis.affected_cohort)
        valid_events=[event for event in hypothesis.resolved_events
          if event not in _unusable_events(hypothesis,deps)]
        valid_evidence=[]
        for evidence in hypothesis.evidence:
            result=deps.query_results.get(evidence.query_id)
            if result is None:continue
            values=_numeric_values(result.rows)
            if not _contains(values,evidence.observed_value):continue
            if evidence.sample_size not in {int(v) for v in values if float(v).is_integer()}:continue
            if any(chunk not in deps.source_chunks for chunk in evidence.source_chunk_ids):continue
            valid_evidence.append(evidence)
        removed_events=len(hypothesis.resolved_events)-len(valid_events)
        removed_evidence=len(hypothesis.evidence)-len(valid_evidence)
        limitations=list(hypothesis.limitations)
        if removed_events or removed_evidence:
            limitations.append(
              f"System B omitted {removed_evidence} unsupported evidence record(s) and "
              f"{removed_events} unresolved event reference(s) during safe report sanitation."
            )
        sanitized.append(hypothesis.model_copy(update={"resolved_events":valid_events,
          "evidence":valid_evidence,"limitations":limitations or ["Evidence remains observational and incomplete."]}))
    return report.model_copy(update={"hypotheses":sanitized})


def _unusable_events(hypothesis,deps:SystemBDependencies)->set[str]:
    unusable=set()
    for event in hypothesis.resolved_events:
        resolution=deps.event_resolutions.get(event)
        if (not resolution or not resolution.resolved or not resolution.selected
                or resolution.selected.confidence<.65):unusable.add(event)
    return unusable


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
