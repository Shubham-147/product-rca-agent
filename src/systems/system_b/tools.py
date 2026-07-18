"""Narrow typed tools exposed to the single Pydantic AI agent."""
from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.analytics import SUPPORTED_DIMENSIONS, SUPPORTED_METRICS
from src.database import QueryResult
from src.guardrails import BLOCKED_PATTERNS, GuardrailError, compile_cohort, require_resolved_event
from src.observability import log_retrieved_chunks
from src.retrieval import RetrievalMode
from src.schemas import CohortDefinition

from .dependencies import SystemBDependencies


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    instance_id: str = Field(min_length=1)


class SearchKnowledgeInput(ToolInput):
    query: str = Field(min_length=1)
    document_types: list[Literal["taxonomy", "prd", "ticket", "funnel", "metric"]]
    screen: str | None = None
    retrieval_mode: RetrievalMode
    top_k: int = Field(default=8, ge=1, le=8)


class ResolveEventsInput(ToolInput):
    concept: str = Field(min_length=1)
    screen: str | None = None
    funnel: str | None = None


class InstanceSummaryInput(ToolInput): pass


class BuildFunnelInput(ToolInput):
    canonical_steps: list[str] = Field(min_length=2)
    same_session: bool = True


class CompareMetricInput(ToolInput):
    metric: str
    dimension: str
    cohort: CohortDefinition | None = None
    minimum_users: int = Field(default=30, ge=1)


class EventSequenceInput(ToolInput):
    start_event: str
    intermediate_events: list[str] = Field(default_factory=list)
    outcome_event: str
    cohort: CohortDefinition | None = None


class ExposedControlInput(ToolInput):
    exposure_definition: CohortDefinition
    control_definition: CohortDefinition
    outcome: str


class ConfounderTestInput(ToolInput):
    confounder: str = Field(min_length=1)
    metric: str
    dimension: str
    cohort: CohortDefinition | None = None
    minimum_users: int = Field(default=30, ge=1)


class MaterializeCohortInput(ToolInput):
    hypothesis_id: str = Field(min_length=1)
    cohort: CohortDefinition


class SystemBTools:
    def __init__(self, deps: SystemBDependencies): self.deps = deps

    def search_knowledge(self, args: SearchKnowledgeInput):
        self._scope(args)
        lowered=args.query.lower()
        if any(pattern in lowered for pattern in BLOCKED_PATTERNS):
            raise GuardrailError("knowledge query references protected data")
        def call():
            query = f"{args.query} {args.screen or ''}".strip()
            allowed = set(args.document_types)
            hits = self.deps.retriever.retrieve(query, args.retrieval_mode, top_k=args.top_k)
            chunks = [hit.chunk for hit in hits if hit.chunk.document_type in allowed][:args.top_k]
            self.deps.source_chunks.update(chunk.chunk_id for chunk in chunks)
            log_retrieved_chunks(self.deps.run_logger,system_name="system_b",
              stage=f"tool_result:{args.retrieval_mode.value}",chunks=chunks)
            return [{"chunk_id": c.chunk_id, "document_type": c.document_type,
                     "text": c.text, "metadata": c.metadata} for c in chunks]
        return self._execute("search_knowledge", "retrieval", args, call)

    def resolve_events(self, args: ResolveEventsInput):
        self._scope(args)
        def call():
            resolution = self.deps.event_resolver.resolve(args.concept, screen=args.screen,
                funnel_name=args.funnel, top_k=5)
            guarded = require_resolved_event(resolution, args.concept)
            self.deps.event_resolutions[guarded.canonical_event] = resolution
            self.deps.safe_query_executor.set_alias_mappings(self.deps.event_resolver.alias_mappings())
            return resolution.model_dump(mode="json")
        return self._execute("resolve_events", "retrieval", args, call)

    def get_instance_summary(self, args: InstanceSummaryInput):
        return self._query("get_instance_summary", args, lambda: self.deps.analytics.get_instance_summary(args.instance_id))

    def build_funnel(self, args: BuildFunnelInput):
        self._require_events(args.canonical_steps)
        return self._query("build_funnel", args, lambda: self.deps.analytics.get_ordered_funnel(
            args.instance_id, args.canonical_steps, args.same_session))

    def compare_metric_by_dimension(self, args: CompareMetricInput):
        if args.metric not in SUPPORTED_METRICS or args.dimension not in SUPPORTED_DIMENSIONS:
            raise GuardrailError("unsupported metric or dimension")
        self._cohort(args.cohort)
        return self._query("compare_metric_by_dimension", args, lambda: self.deps.analytics.compare_metric_by_dimension(
            args.instance_id, args.metric, args.dimension, args.cohort, args.minimum_users))

    def analyse_event_sequence(self, args: EventSequenceInput):
        self._require_events([args.start_event, *args.intermediate_events, args.outcome_event]);self._cohort(args.cohort)
        return self._query("analyse_event_sequence", args, lambda: self.deps.analytics.analyse_event_sequence(
            args.instance_id, args.start_event, args.intermediate_events, args.outcome_event, args.cohort))

    def compare_exposed_unexposed(self, args: ExposedControlInput):
        self._require_events([args.outcome]);self._cohort(args.exposure_definition);self._cohort(args.control_definition)
        return self._query("compare_exposed_unexposed", args, lambda: self.deps.analytics.compare_exposed_unexposed(
            args.instance_id, args.exposure_definition, args.control_definition, args.outcome))

    def test_confounder(self, args: ConfounderTestInput):
        if args.metric not in SUPPORTED_METRICS or args.dimension not in SUPPORTED_DIMENSIONS:
            raise GuardrailError("unsupported confounder test")
        self._cohort(args.cohort)
        return self._query("test_confounder", args, lambda: self.deps.analytics.compare_metric_by_dimension(
            args.instance_id, args.metric, args.dimension, args.cohort, args.minimum_users))

    def materialize_cohort(self, args: MaterializeCohortInput):
        self._cohort(args.cohort)
        result = self._query("materialize_cohort", args, lambda: self.deps.cohort_materializer(
            self.deps.run_id, "system_b", args.hypothesis_id, args.cohort))
        self.deps.materialized_hypotheses.add(args.hypothesis_id);return result

    def _query(self, name, args, fn):
        result, cached = self._execute(name, "analytical", args, fn, with_cache=True)
        result = self.deps.remember_query(result)
        return result.model_dump(mode="json") if isinstance(result, QueryResult) else result

    def _execute(self, name, kind, args, fn, with_cache=False):
        self._scope(args);started=time.perf_counter()
        try:
            result,cached=self.deps.guardrail_service.execute(name,kind,args,fn)
            query = result if isinstance(result,QueryResult) else None
            event={"tool":name,"arguments":args.model_dump(mode="json"),"query_id":query.query_id if query else None,
                "result_summary":query.result_summary if query else f"{len(result)} retrieved chunks",
                "duration_ms":(time.perf_counter()-started)*1000,"cache_status":"hit" if cached else "miss"}
            self.deps.tool_events.append(event)
            self.deps.run_logger.log(tool=name,arguments=event["arguments"],query_id=event["query_id"],sql=query.executed_sql if query else None,
                parameters=query.parameters if query else None,result_size=query.row_count if query else len(result),
                result_summary=event["result_summary"],duration_ms=event["duration_ms"],cache_status=event["cache_status"])
            return (result,cached) if with_cache else result
        except Exception as exc:
            self.deps.run_logger.log(tool=name,duration_ms=(time.perf_counter()-started)*1000,error=exc);raise

    def _scope(self,args):
        if args.instance_id != self.deps.instance_id:raise GuardrailError("tool instance_id does not match the active run")
    def _cohort(self,cohort):
        if cohort is not None:compile_cohort(self.deps.instance_id,cohort)
    def _require_events(self,events):
        unresolved=[event for event in events if event not in self.deps.event_resolutions]
        if unresolved:raise GuardrailError(f"events must be resolved before analytics: {unresolved}")
