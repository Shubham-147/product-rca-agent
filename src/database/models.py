"""Typed query envelopes returned by deterministic analytics."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str
    executed_sql: str
    parameters: list[Any] = Field(default_factory=list)
    duration_ms: float = Field(ge=0)
    row_count: int = Field(ge=0)
    result_summary: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
