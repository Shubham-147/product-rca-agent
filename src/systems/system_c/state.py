"""Aggregate-only LangGraph state for System C."""
from __future__ import annotations
from typing import Any,TypedDict
from src.database import QueryResult
from src.retrieval.schemas import EventResolution
from src.schemas import AnalysisRequest,RCAReport
from .models import *

class SystemCState(TypedDict,total=False):
    request:AnalysisRequest
    instance_summary:QueryResult
    retrieved_context:list[dict[str,Any]]
    candidate_hypotheses:list[CandidateHypothesis]
    current_hypothesis:CandidateHypothesis|None
    current_hypothesis_index:int
    resolved_events:dict[str,EventResolution]
    query_plan:TypedQueryPlan|None
    query_results:list[QueryResult]
    validation_result:ValidationResult|None
    falsification_result:FalsificationResult|None
    accepted_hypotheses:list[AcceptedHypothesis]
    rejected_hypotheses:list[RejectedHypothesis]
    revision_count:int
    revisions_by_hypothesis:dict[str,int]
    maximum_revisions:int
    node_execution_count:int
    context_retry_used:bool
    ranked_hypotheses:list[AcceptedHypothesis]
    report:RCAReport|None
    trace:list[dict[str,Any]]
    errors:list[str]
    warnings:list[str]
