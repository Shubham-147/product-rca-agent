"""Shared structured outputs for all root-cause systems."""

from pydantic import BaseModel, Field


class Hypothesis(BaseModel):
    """A system's proposed explanation for a product symptom."""

    mechanism: str = Field(min_length=1)
    affected_cohort: list[str] | str
    evidence: list[str]
    confounders_ruled_out: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

