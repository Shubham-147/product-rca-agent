"""The agent-facing tools — thin, typed, guarded wrappers over the foundation.

Each tool takes the run's `Deps` (the warehouse-bound compiler + the spec index) plus
typed *intent*, and returns a validated result or a `ToolError` with a `hint` the agent
can act on. Tools never raise and never accept raw SQL: the cohort/segment intent is a
DSL, so there is no injection surface (design decisions D3/D8).

These are framework-agnostic functions; the Pydantic-AI agent (Phase 2) registers them
with a RunContext[Deps]. Building them here lets us prove the full toolset deterministically
before any LLM is wired in.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..analytics import FUNNEL_STEPS, Analytics
from ..contracts import Cohort
from ..retrieval.query import resolve_events as _resolve_events
from ..retrieval.spec import SpecIndex, get_spec_index
from ..warehouse import COHORT_COLS, Warehouse
from .schemas import (
    CohortResult, EventCandidate, EventResolution, FunnelResult, FunnelStep,
    MetricResult, MetricValue, SpecHit, SpecResult, ToolError,
)

# Metrics metric_by_segment understands (mirrors analytics._metric_expr). Surfaced in
# the ToolError hint so a bad call teaches the agent the valid vocabulary.
VALID_METRICS = (
    "conversion:<from>-><to>", "checkout_p95", "cold_start_p95", "screen_p95:<screen>",
    "crash_rate", "payment_error_rate",
)


@dataclass
class Deps:
    """Everything a tool needs for one instance — bound at run start."""

    analytics: Analytics
    spec: SpecIndex

    @classmethod
    def for_task(cls, task_path: str) -> "Deps":
        wh = Warehouse.from_task(task_path)
        return cls(analytics=Analytics(wh), spec=get_spec_index())

    @classmethod
    def for_warehouse(cls, warehouse_path: str) -> "Deps":
        return cls(analytics=Analytics(Warehouse(warehouse_path)), spec=get_spec_index())


# --------------------------------------------------------------------------- tools
def funnel(deps: Deps, segment_by: list[str] | None = None) -> FunnelResult | ToolError:
    """Session-level step conversion pre vs post, optionally sliced by user attributes."""
    try:
        rows = deps.analytics.funnel(segment_by or [])
    except Exception as e:  # fail typed (tenet #7): never crash the run
        return ToolError(error=str(e), hint=f"segment_by must be a subset of {list(COHORT_COLS)}")
    return FunnelResult(
        segmented_by=segment_by or [],
        steps=[FunnelStep(**vars(r)) for r in rows],
    )


def metric_by_segment(
    deps: Deps,
    metric: str,
    segment_by: list[str] | None = None,
    where: Cohort | None = None,
) -> MetricResult | ToolError:
    """A named metric sliced by segment(s), pre vs post, with deltas.

    `where` is a Cohort DSL (compiled to SQL here) — the tool never takes raw SQL."""
    try:
        where_sql = where.to_sql() if where else None
        rows = deps.analytics.metric_by_segment(metric, segment_by or [], where=where_sql)
    except Exception as e:  # fail typed (tenet #7)
        hint = f"valid metrics: {', '.join(VALID_METRICS)}"
        if "segment" in str(e):
            hint = f"segment_by must be a subset of {list(COHORT_COLS)}"
        return ToolError(error=str(e), hint=hint)
    return MetricResult(
        metric=metric, segmented_by=segment_by or [], where=where_sql,
        rows=[MetricValue(**vars(r)) for r in rows],
    )


def cohort_resolve(deps: Deps, cohort: Cohort) -> CohortResult | ToolError:
    """Compile a Cohort predicate to its user-id set size (the affected-population count)."""
    try:
        res = deps.analytics.cohort_resolve(cohort)
    except Exception as e:  # fail typed (tenet #7)
        return ToolError(error=str(e),
                         hint="check op/value coherence (op 'in' needs a list; others a scalar)")
    return CohortResult(predicate=res.predicate, n_users=res.n_users)


def resolve_events(query: str, k: int = 8) -> EventResolution | ToolError:
    """Resolve a cursed / free-text event term to ranked canonical event concepts."""
    try:
        r = _resolve_events(query, k=k)
    except Exception as e:  # fail typed (tenet #7)
        return ToolError(error=str(e), hint="pass a short event term, e.g. 'checkout'")
    return EventResolution(
        query=r.query, resolved=r.resolved, confidence=r.confidence,
        candidates=[EventCandidate(name=c.name, score=c.score) for c in r.candidates],
    )


def retrieve_spec(deps: Deps, query: str, k: int = 4) -> SpecResult | ToolError:
    """Dense RAG over the PRD (+ tickets) — the product's intent / SLOs / design choices."""
    try:
        hits = deps.spec.query(query, k=k)
    except Exception as e:  # fail typed (tenet #7)
        return ToolError(error=str(e), hint="pass a natural-language question about the product")
    return SpecResult(query=query, hits=[SpecHit(**vars(h)) for h in hits])


# The canonical funnel, handy for prompts/UX (agents don't have to guess step names).
FUNNEL = list(FUNNEL_STEPS)
