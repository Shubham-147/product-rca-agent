"""Shared retrieval result models."""

from pydantic import BaseModel


class TaxonomyHit(BaseModel):
    """One ranked taxonomy search result."""

    event_name: str
    score: float
    description: str

