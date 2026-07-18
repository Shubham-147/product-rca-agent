"""Provider-agnostic data contracts shared by all three RCA systems."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    """Strict base model for stable boundaries between system components."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TimeWindow(ContractModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_order(self) -> "TimeWindow":
        if self.end <= self.start:
            raise ValueError("end must be later than start")
        return self


class AnalysisRequest(ContractModel):
    instance_id: str = Field(min_length=1)
    symptom: str = Field(min_length=1)
    funnel_name: str | None = None
    suspected_screen: str | None = None
    incident_window: TimeWindow | None = None
    baseline_window: TimeWindow | None = None


class CohortDefinition(ContractModel):
    instance_id: str = Field(min_length=1)
    os: str | None = None
    device_type: str | None = None
    device_age_min: int | None = Field(default=None, ge=0)
    device_age_max: int | None = Field(default=None, ge=0)
    geo: str | None = None
    channel: str | None = None
    is_returning: bool | None = None
    payment_method: str | None = None
    required_events: list[str] = Field(default_factory=list)
    excluded_events: list[str] = Field(default_factory=list)
    had_crash: bool | None = None
    minimum_latency_ms: float | None = Field(default=None, ge=0)
    description: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_device_age_range(self) -> "CohortDefinition":
        if (
            self.device_age_min is not None
            and self.device_age_max is not None
            and self.device_age_min > self.device_age_max
        ):
            raise ValueError("device_age_min cannot exceed device_age_max")
        return self


class Evidence(ContractModel):
    evidence_id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    metric_name: str = Field(min_length=1)
    observed_value: float
    comparison_value: float | None = None
    sample_size: int = Field(ge=0)
    query_id: str = Field(min_length=1)
    source_chunk_ids: list[str] = Field(default_factory=list)


class ConfounderTest(ContractModel):
    confounder: str = Field(min_length=1)
    method: str = Field(min_length=1)
    result: str = Field(min_length=1)
    status: Literal["supported", "ruled_out", "inconclusive"]


class RootCauseHypothesis(ContractModel):
    hypothesis_id: str = Field(min_length=1)
    rank: int = Field(ge=1)
    mechanism: str = Field(min_length=1)
    affected_cohort: CohortDefinition
    resolved_events: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    confounders: list[ConfounderTest] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    limitations: list[str] = Field(default_factory=list)


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RunMetadata(ContractModel):
    run_id: str = Field(min_length=1)
    system_name: Literal["system_a", "system_b", "system_c"]
    instance_id: str = Field(min_length=1)
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completion_time: datetime | None = None
    status: RunStatus = RunStatus.RUNNING

    @model_validator(mode="after")
    def validate_completion(self) -> "RunMetadata":
        if self.completion_time is not None and self.completion_time < self.start_time:
            raise ValueError("completion_time cannot be earlier than start_time")
        if self.status == RunStatus.COMPLETED and self.completion_time is None:
            raise ValueError("completed runs require completion_time")
        return self


class RCAReport(ContractModel):
    instance_id: str = Field(min_length=1)
    symptom: str = Field(min_length=1)
    hypotheses: list[RootCauseHypothesis] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    run_metadata: RunMetadata

    @model_validator(mode="after")
    def validate_instance_ids(self) -> "RCAReport":
        if self.run_metadata.instance_id != self.instance_id:
            raise ValueError("run metadata instance_id must match report instance_id")
        if any(h.affected_cohort.instance_id != self.instance_id for h in self.hypotheses):
            raise ValueError("all hypothesis cohorts must match report instance_id")
        ranks = [hypothesis.rank for hypothesis in self.hypotheses]
        if len(ranks) != len(set(ranks)):
            raise ValueError("hypothesis ranks must be unique")
        return self
