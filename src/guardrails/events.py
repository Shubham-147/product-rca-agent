"""Confidence-aware event-resolution boundary."""
from __future__ import annotations
from dataclasses import dataclass
from src.retrieval.schemas import EventResolution
from .errors import GuardrailError

@dataclass(frozen=True)
class GuardedEvent:
    canonical_event:str
    raw_event_name:str|None
    confidence:float
    warning:str|None=None

def require_resolved_event(resolution:EventResolution,raw_event_name:str|None=None)->GuardedEvent:
    if not resolution.resolved or resolution.selected is None or resolution.selected.confidence<.65:
        raise GuardrailError("unresolved or low-confidence event cannot be queried automatically")
    warning=None
    if resolution.selected.confidence<.85:
        warning="medium-confidence event mapping; verify before automatic use"
    return GuardedEvent(resolution.selected.canonical_event,raw_event_name,
                        resolution.selected.confidence,warning)
