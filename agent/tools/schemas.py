"""Typed tool I/O — the agent boundary (design tenet #2).

Every tool returns a validated Pydantic result *or* a `ToolError` (never raises). These
models are what the agent's tool-calling layer serializes, what the trace records, and
what the UI renders — one definition, three consumers.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..contracts import ToolError

__all__ = [
    "ToolError", "FunnelStep", "FunnelResult", "MetricValue", "MetricResult",
    "CohortResult", "EventCandidate", "EventResolution", "SpecHit", "SpecResult",
]


class FunnelStep(BaseModel):
    step_from: str
    step_to: str
    segment: dict[str, object] = {}
    conv_pre: float | None
    conv_post: float | None
    delta_pp: float | None
    denom_pre: int
    denom_post: int


class FunnelResult(BaseModel):
    segmented_by: list[str] = []
    steps: list[FunnelStep]


class MetricValue(BaseModel):
    segment: dict[str, object] = {}
    value_pre: float | None
    value_post: float | None
    delta: float | None
    n_pre: int
    n_post: int


class MetricResult(BaseModel):
    metric: str
    segmented_by: list[str] = []
    where: str | None = None
    rows: list[MetricValue]


class CohortResult(BaseModel):
    predicate: str
    n_users: int
    note: str = ""  # set when the cohort matches 0 users (likely a wrong attribute value)


class EventCandidate(BaseModel):
    name: str
    score: float


class EventResolution(BaseModel):
    query: str
    resolved: str
    confidence: float
    candidates: list[EventCandidate]


class SpecHit(BaseModel):
    chunk_id: str
    source: str
    heading: str
    score: float
    text: str


class SpecResult(BaseModel):
    query: str
    hits: list[SpecHit]
