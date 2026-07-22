"""Agent-facing tool layer: typed, guarded wrappers over the deterministic foundation."""

from .core import (
    FUNNEL,
    Deps,
    cohort_resolve,
    funnel,
    metric_by_segment,
    resolve_events,
    retrieve_spec,
)
from .schemas import ToolError

__all__ = [
    "Deps", "funnel", "metric_by_segment", "cohort_resolve", "resolve_events",
    "retrieve_spec", "ToolError", "FUNNEL",
]
