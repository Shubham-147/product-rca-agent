"""Typed internal contracts for System C's graph nodes."""
from __future__ import annotations
from typing import Literal,Any
from pydantic import BaseModel,ConfigDict,Field
from src.schemas import CohortDefinition,Evidence,ConfounderTest,RootCauseHypothesis

class GraphModel(BaseModel):model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)

class CandidateHypothesis(GraphModel):
    hypothesis_id:str
    proposed_mechanism:str
    expected_cohort:CohortDefinition
    required_events:list[str]=Field(default_factory=list)
    expected_observations:list[str]=Field(default_factory=list)
    alternative_explanations:list[str]=Field(default_factory=list)
    possible_confounders:list[str]=Field(default_factory=list)
    benign_explanation:bool=False
    context_chunk_ids:list[str]=Field(default_factory=list)

class HypothesisBatch(GraphModel):
    hypotheses:list[CandidateHypothesis]=Field(min_length=3,max_length=5)

class QueryPlanItem(GraphModel):
    query_key:str
    question:str
    operation:Literal["funnel","metric_by_dimension","event_sequence","exposed_control"]
    metric:str|None=None
    dimension:str|None=None
    cohort:CohortDefinition|None=None
    exposure:CohortDefinition|None=None
    control:CohortDefinition|None=None
    expected_observation_if_true:str
    potential_confounder:str|None=None
    required_canonical_events:list[str]=Field(default_factory=list)
    same_session:bool=True

class TypedQueryPlan(GraphModel):items:list[QueryPlanItem]=Field(min_length=1)

class ValidationResult(GraphModel):
    supported:bool
    sufficient_sample:bool
    denominator_valid:bool
    event_resolution_valid:bool
    temporal_order_valid:bool
    cohort_valid:bool
    evidence_consistent:bool
    query_ids:list[str]=Field(default_factory=list)
    reasons:list[str]=Field(default_factory=list)

class FalsificationResult(GraphModel):
    verdict:Literal["pass","revise","reject"]
    counter_evidence:list[Evidence]=Field(default_factory=list)
    confounders_found:list[ConfounderTest]=Field(default_factory=list)
    additional_queries:list[str]=Field(default_factory=list)
    revision_instruction:str|None=None
    falsification_summary:str
    falsification_score:float=Field(ge=0,le=1)

class AcceptedHypothesis(GraphModel):
    hypothesis:CandidateHypothesis
    evidence:list[Evidence]
    confounders:list[ConfounderTest]=Field(default_factory=list)
    limitations:list[str]=Field(default_factory=list)
    evidence_strength:float=Field(ge=0,le=1)
    effect_size_score:float=Field(ge=0,le=1)
    cohort_specificity:float=Field(ge=0,le=1)
    temporal_precedence:float=Field(ge=0,le=1)
    falsification_resistance:float=Field(ge=0,le=1)
    rank_score:float=0
    rank:int|None=None
    materialized_query_id:str|None=None

class RejectedHypothesis(GraphModel):hypothesis_id:str;reason:str

class RevisionOutput(GraphModel):hypothesis:CandidateHypothesis
