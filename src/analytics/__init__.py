"""Public deterministic analytics shared by systems A, B, and C."""

from __future__ import annotations

from typing import Sequence

from src.database import QueryResult
from src.schemas import CohortDefinition

from .service import DeterministicAnalytics, SUPPORTED_DIMENSIONS, SUPPORTED_METRICS


def get_instance_summary(instance_id: str) -> QueryResult:
    return DeterministicAnalytics().get_instance_summary(instance_id)


def get_naive_funnel(instance_id: str, canonical_steps: Sequence[str]) -> QueryResult:
    return DeterministicAnalytics().get_naive_funnel(instance_id, canonical_steps)


def get_ordered_funnel(
    instance_id: str, canonical_steps: Sequence[str], same_session: bool = True
) -> QueryResult:
    return DeterministicAnalytics().get_ordered_funnel(
        instance_id, canonical_steps, same_session
    )


def compare_metric_by_dimension(
    instance_id: str,
    metric: str,
    dimension: str,
    cohort: CohortDefinition | dict | None = None,
    minimum_users: int = 30,
    screen: str | None = None,
) -> QueryResult:
    return DeterministicAnalytics().compare_metric_by_dimension(
        instance_id, metric, dimension, cohort, minimum_users, screen
    )


def analyse_event_sequence(
    instance_id: str,
    start_event: str,
    intermediate_events: Sequence[str],
    outcome_event: str,
    cohort: CohortDefinition | dict | None = None,
) -> QueryResult:
    return DeterministicAnalytics().analyse_event_sequence(
        instance_id, start_event, intermediate_events, outcome_event, cohort
    )


def compare_exposed_unexposed(
    instance_id: str,
    exposure_definition: CohortDefinition | dict,
    control_definition: CohortDefinition | dict,
    outcome: str,
) -> QueryResult:
    return DeterministicAnalytics().compare_exposed_unexposed(
        instance_id, exposure_definition, control_definition, outcome
    )


def materialize_cohort(
    run_id: str,
    system_name: str,
    hypothesis_id: str,
    cohort_definition: CohortDefinition | dict,
) -> QueryResult:
    return DeterministicAnalytics().materialize_cohort(
        run_id, system_name, hypothesis_id, cohort_definition
    )


def get_debug_sample(
    instance_id: str, *, user_limit: int = 20, event_limit: int = 50
) -> QueryResult:
    return DeterministicAnalytics().get_debug_sample(
        instance_id, user_limit=user_limit, event_limit=event_limit
    )


__all__ = [
    "DeterministicAnalytics", "SUPPORTED_DIMENSIONS", "SUPPORTED_METRICS",
    "analyse_event_sequence", "compare_exposed_unexposed",
    "compare_metric_by_dimension", "get_debug_sample", "get_instance_summary",
    "get_naive_funnel", "get_ordered_funnel", "materialize_cohort",
]
