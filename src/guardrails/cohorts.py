"""Compile typed cohort definitions into parameterized SQL predicates."""

from __future__ import annotations

from src.schemas import CohortDefinition

from .errors import GuardrailError


def compile_cohort(
    instance_id: str,
    cohort: CohortDefinition | dict | None,
    *,
    user_alias: str = "u",
) -> tuple[str, list[object]]:
    if not instance_id.strip():
        raise GuardrailError("instance_id is required")
    if cohort is None:
        return f"{user_alias}.instance_id = ?", [instance_id]
    definition = cohort if isinstance(cohort, CohortDefinition) else CohortDefinition.model_validate(cohort)
    if definition.instance_id != instance_id:
        raise GuardrailError("cohort instance_id does not match analytical instance_id")

    clauses = [f"{user_alias}.instance_id = ?"]
    params: list[object] = [instance_id]
    scalar_fields = {
        "os": definition.os,
        "device_type": definition.device_type,
        "geo": definition.geo,
        "channel": definition.channel,
        "is_returning": definition.is_returning,
    }
    for column, value in scalar_fields.items():
        if value is not None:
            clauses.append(f"{user_alias}.{column} = ?")
            params.append(value.lower().strip() if isinstance(value, str) else value)
    if definition.device_age_min is not None:
        clauses.append(f"{user_alias}.device_age_months >= ?")
        params.append(definition.device_age_min)
    if definition.device_age_max is not None:
        clauses.append(f"{user_alias}.device_age_months <= ?")
        params.append(definition.device_age_max)

    event_filters = ["e.instance_id = u.instance_id", "e.user_id = u.user_id"]
    event_params: list[object] = []
    if definition.payment_method is not None:
        event_filters.append("e.payment_method = ?")
        event_params.append(definition.payment_method.lower().strip())
    if definition.had_crash is not None:
        event_filters.append("e.is_crash = ?")
        event_params.append(definition.had_crash)
    if definition.minimum_latency_ms is not None:
        event_filters.append("e.latency_ms >= ?")
        event_params.append(definition.minimum_latency_ms)
    if len(event_filters) > 2:
        clauses.append(f"EXISTS (SELECT 1 FROM v_events e WHERE {' AND '.join(event_filters)})")
        params.extend(event_params)
    for event in definition.required_events:
        clauses.append(
            "EXISTS (SELECT 1 FROM v_events e WHERE e.instance_id = u.instance_id "
            "AND e.user_id = u.user_id AND e.event_name = ?)"
        )
        params.append(event.lower().strip())
    for event in definition.excluded_events:
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM v_events e WHERE e.instance_id = u.instance_id "
            "AND e.user_id = u.user_id AND e.event_name = ?)"
        )
        params.append(event.lower().strip())
    return " AND ".join(clauses), params
