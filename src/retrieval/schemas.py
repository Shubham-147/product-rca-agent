"""Text-corpus and retrieval contracts."""
from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")

class TaxonomyRecord(Model):
    canonical_event: str
    aliases: list[str] = Field(default_factory=list)
    description: str
    screen: str | None = None
    funnel_step: str | None = None
    event_category: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    is_expected_dropoff: bool = False
    valid_predecessors: list[str] = Field(default_factory=list)
    valid_successors: list[str] = Field(default_factory=list)

class PRDSection(Model):
    heading: str
    content: str
    children: list["PRDSection"] = Field(default_factory=list)

class PRDDocument(Model):
    document_id: str
    title: str
    version: str
    sections: list[PRDSection] = Field(default_factory=list)

class TicketDocument(Model):
    ticket_id: str
    title: str
    description: str
    affected_screen: str | None = None
    symptoms: list[str] = Field(default_factory=list)
    investigation_notes: str | None = None
    resolution: str | None = None
    status: str

class FunnelDefinition(Model):
    funnel_name: str
    canonical_steps: list[str]
    alternative_paths: list[list[str]] = Field(default_factory=list)
    optional_steps: list[str] = Field(default_factory=list)
    expected_dropoff_steps: list[str] = Field(default_factory=list)

class MetricDefinition(Model):
    metric_name: str
    numerator: str
    denominator: str
    grain: str
    required_events: list[str] = Field(default_factory=list)
    minimum_sample_size: int = Field(ge=1)
    limitations: list[str] = Field(default_factory=list)

class Chunk(Model):
    chunk_id: str
    document_type: str
    document_id: str
    text: str
    content_hash: str
    parent_chunk_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class RetrievalMode(str, Enum):
    EVENT_RESOLUTION="event_resolution"
    PRODUCT_INTENT="product_intent"
    HISTORICAL_TICKET="historical_ticket"
    METRIC_DEFINITION="metric_definition"

class RetrievedChunk(Model):
    chunk: Chunk
    dense_rank: int | None = None
    sparse_rank: int | None = None
    fused_score: float = 0
    rerank_score: float | None = None

class CanonicalCandidate(Model):
    canonical_event: str
    aliases: list[str]
    matched_aliases: list[str] = Field(default_factory=list)
    screen: str | None = None
    confidence: float = Field(ge=0, le=1)
    resolution_method: str
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

class EventResolution(Model):
    concept: str
    candidates: list[CanonicalCandidate] = Field(default_factory=list)
    resolved: bool
    selected: CanonicalCandidate | None = None
    warnings: list[str] = Field(default_factory=list)

class AliasMapping(Model):
    raw_event_name: str
    canonical_event: str | None = None
    is_resolved: bool
    funnel_step: str | None = None
    is_expected_dropoff: bool = False
    taxonomy_version: str
