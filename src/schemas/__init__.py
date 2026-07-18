"""Shared Pydantic contracts for Product RCA systems A, B, and C."""

from .models import (
    AnalysisRequest,
    CohortDefinition,
    ConfounderTest,
    Evidence,
    RCAReport,
    RootCauseHypothesis,
    RunMetadata,
    RunStatus,
    TimeWindow,
)

__all__ = [
    "AnalysisRequest",
    "CohortDefinition",
    "ConfounderTest",
    "Evidence",
    "RCAReport",
    "RootCauseHypothesis",
    "RunMetadata",
    "RunStatus",
    "TimeWindow",
]
