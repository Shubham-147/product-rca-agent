"""System A: deliberately simple, taxonomy-only vanilla RAG baseline."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable

from pydantic import ValidationError

from src.retrieval.hybrid import resolve_event
from src.retrieval.models import TaxonomyHit
from src.systems.llm_client import LLMClient
from src.systems.schema import Hypothesis

logger = logging.getLogger(__name__)

Resolver = Callable[[str, int], list[TaxonomyHit]]


class SystemA:
    """Retrieve taxonomy text once and ask an LLM for one hypothesis.

    This baseline intentionally has no SQL access, aggregation, cohort computation,
    counterfactual test, or validation loop.
    """

    def __init__(self, llm: LLMClient, resolver: Resolver = resolve_event) -> None:
        self.llm = llm
        self.resolver = resolver

    def analyze(self, question: str, top_k: int = 5) -> Hypothesis:
        """Return a schema-validated, but deliberately unvalidated, hypothesis."""
        if not question.strip():
            raise ValueError("question must not be empty")
        hits = self.resolver(question, top_k)
        context = "\n".join(
            f"- {hit.event_name}: {hit.description}" for hit in hits
        )
        prompt = f"""You are System A, a vanilla taxonomy RAG baseline.
Given the symptom and retrieved taxonomy text below, propose one root-cause hypothesis.
Do not claim that SQL, event aggregation, or cohort validation was performed.

Symptom:
{question}

Retrieved taxonomy context:
{context}

Return JSON only with exactly these fields:
mechanism (string), affected_cohort (filter description or user_id list),
evidence (list of strings), confounders_ruled_out (list), confidence (0 to 1).
"""
        raw = self.llm.complete(prompt)
        hypothesis = _parse_hypothesis(raw)
        logger.warning(
            "System A hypothesis is not grounded in SQL query results; "
            "affected_cohort is an LLM description, not a computed user cohort."
        )
        return hypothesis


def _parse_hypothesis(raw: str) -> Hypothesis:
    """Validate JSON output, tolerating a single Markdown JSON fence."""
    text = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        payload = json.loads(text)
        return Hypothesis.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(
            "System A LLM output was not a valid Hypothesis JSON object."
        ) from exc

