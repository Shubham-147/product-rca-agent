from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from simulator.schemas import Hypothesis


class SystemAOutput(BaseModel):
    """Strict persisted output produced by the one LLM generation call."""

    model_config = ConfigDict(extra="forbid")
    instance_id: str
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=3)


class RetrievedChunk(BaseModel):
    chunk_id: str
    source: str
    score: float
    text: str
