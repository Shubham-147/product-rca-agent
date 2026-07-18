"""Deterministic, aggregated analytics over the guarded DuckDB layer."""

from __future__ import annotations

from typing import Sequence

from src.database import DuckDBManager, QueryResult, get_duckdb_manager
from src.guardrails import GuardrailError, compile_cohort
from src.schemas import CohortDefinition

SUPPORTED_DIMENSIONS = {
    "os", "device_type", "device_age_bucket", "geo", "channel",
    "is_returning", "payment_method", "screen",
}
SUPPORTED_METRICS = {
    "users", "crash_rate", "checkout_crash_rate", "checkout_completion_rate",
    "payment_completion_rate", "latency_p50", "latency_p95",
}


class DeterministicAnalytics:
    def __init__(self, manager: DuckDBManager | None = None) -> None:
        self.manager = manager or get_duckdb_manager()

    @property
    def event_relation(self) -> str:
        return "v_events_resolved" if self.manager.has_resolved_events else "v_events"

    @property
    def event_column(self) -> str:
        return "canonical_event" if self.manager.has_resolved_events else "event_name"

    def get_instance_summary(self, instance_id: str) -> QueryResult:
        sql = """
            SELECT
                (SELECT count(DISTINCT user_id) FROM v_users WHERE instance_id = ?) AS users,
                (SELECT count(*) FROM v_events WHERE instance_id = ?) AS events,
                (SELECT count(DISTINCT session_id) FROM v_events WHERE instance_id = ?) AS sessions,
                (SELECT min(event_ts) FROM v_events WHERE instance_id = ?) AS first_event_at,
                (SELECT max(event_ts) FROM v_events WHERE instance_id = ?) AS last_event_at
        """
        return self.manager.execute_source(
            instance_id, sql, [instance_id] * 5, summary="instance-level aggregate summary"
        )

    def get_naive_funnel(self, instance_id: str, canonical_steps: Sequence[str]) -> QueryResult:
        steps = _steps(canonical_steps)
        values = ", ".join("(?, ?)" for _ in steps)
        params: list[object] = []
        for position, step in enumerate(steps):
            params.extend([step, position])
        params.append(instance_id)
        sql = f"""
            WITH funnel_steps(event_name, step_order) AS (VALUES {values})
            SELECT f.step_order, f.event_name,
                   count(DISTINCT e.user_id) AS users
            FROM funnel_steps f
            LEFT JOIN v_events e
              ON e.instance_id = ? AND e.event_name = f.event_name
            GROUP BY f.step_order, f.event_name
            ORDER BY f.step_order
        """
        return self.manager.execute_source(
            instance_id, sql, params, summary="unordered distinct-user funnel"
        )

    def get_ordered_funnel(
        self, instance_id: str, canonical_steps: Sequence[str], same_session: bool = True
    ) -> QueryResult:
        steps = _steps(canonical_steps)
        relation, event_column = self.event_relation, self.event_column
        ctes = [f"""step_0 AS (
            SELECT instance_id, user_id, session_id, min(event_ts) AS reached_at
            FROM {relation} WHERE instance_id = ? AND {event_column} = ?
            GROUP BY instance_id, user_id, session_id
        )"""]
        params: list[object] = [instance_id, steps[0]]
        for index, step in enumerate(steps[1:], start=1):
            session_clause = "AND e.session_id = p.session_id" if same_session else ""
            session_select = "p.session_id" if same_session else "e.session_id"
            ctes.append(f"""step_{index} AS (
                SELECT p.instance_id, p.user_id, {session_select} AS session_id, min(e.event_ts) AS reached_at
                FROM step_{index - 1} p
                JOIN {relation} e ON e.instance_id = p.instance_id AND e.user_id = p.user_id
                  {session_clause}
                  AND e.instance_id = ? AND e.{event_column} = ? AND e.event_ts >= p.reached_at
                GROUP BY p.instance_id, p.user_id, {session_select}
            )""")
            params.extend([instance_id, step])
        unions = " UNION ALL ".join(
            f"SELECT {i} AS step_order, '{_sql_literal(step)}' AS event_name, "
            f"count(DISTINCT user_id) AS users FROM step_{i}"
            for i, step in enumerate(steps)
        )
        sql = f"WITH {', '.join(ctes)} {unions} ORDER BY step_order"
        return self.manager.execute_source(
            instance_id, sql, params,
            summary=f"ordered distinct-user funnel (same_session={same_session})",
        )

    def compare_metric_by_dimension(
        self,
        instance_id: str,
        metric: str,
        dimension: str,
        cohort: CohortDefinition | dict | None = None,
        minimum_users: int = 30,
        screen: str | None = None,
    ) -> QueryResult:
        if metric not in SUPPORTED_METRICS:
            raise GuardrailError(f"unsupported metric: {metric}")
        if dimension not in SUPPORTED_DIMENSIONS:
            raise GuardrailError(f"unsupported dimension: {dimension}")
        if minimum_users < 1:
            raise GuardrailError("minimum_users must be positive")
        predicate, params = compile_cohort(instance_id, cohort)
        sql, metric_params = _metric_sql(
            metric, dimension, predicate, instance_id, minimum_users,
            self.event_relation, self.event_column, screen,
        )
        return self.manager.execute_source(
            instance_id,
            sql,
            [*params, *metric_params],
            summary=f"{metric} grouped by {dimension}; minimum_users={minimum_users}",
        )

    def analyse_event_sequence(
        self,
        instance_id: str,
        start_event: str,
        intermediate_events: Sequence[str],
        outcome_event: str,
        cohort: CohortDefinition | dict | None = None,
    ) -> QueryResult:
        events = _steps([start_event, *intermediate_events, outcome_event])
        relation,event_column=self.event_relation,self.event_column
        predicate, cohort_params = compile_cohort(instance_id, cohort)
        ctes = [f"cohort_users AS (SELECT u.instance_id, u.user_id FROM v_users_enriched u WHERE {predicate})"]
        ctes.append(f"""seq_0 AS (
            SELECT e.instance_id, e.user_id, e.session_id, min(e.event_ts) reached_at
            FROM {relation} e JOIN cohort_users c USING (instance_id, user_id)
            WHERE e.instance_id = ? AND e.{event_column} = ?
            GROUP BY e.instance_id, e.user_id, e.session_id
        )""")
        params: list[object] = [*cohort_params, instance_id, events[0]]
        for index, event in enumerate(events[1:], start=1):
            ctes.append(f"""seq_{index} AS (
                SELECT p.instance_id, p.user_id, p.session_id, min(e.event_ts) reached_at
                FROM seq_{index - 1} p JOIN {relation} e
                  ON e.instance_id = p.instance_id AND e.user_id = p.user_id AND e.session_id = p.session_id
                 AND e.instance_id = ? AND e.{event_column} = ? AND e.event_ts >= p.reached_at
                GROUP BY p.instance_id, p.user_id, p.session_id
            )""")
            params.extend([instance_id, event])
        unions = " UNION ALL ".join(
            f"SELECT {i} step_order, '{_sql_literal(event)}' event_name, "
            f"count(DISTINCT user_id) users FROM seq_{i}"
            for i, event in enumerate(events)
        )
        return self.manager.execute_source(
            instance_id, f"WITH {', '.join(ctes)} {unions} ORDER BY step_order", params,
            summary="same-session ordered event sequence",
        )

    def compare_exposed_unexposed(
        self,
        instance_id: str,
        exposure_definition: CohortDefinition | dict,
        control_definition: CohortDefinition | dict,
        outcome: str,
    ) -> QueryResult:
        exposed_sql, exposed_params = compile_cohort(instance_id, exposure_definition)
        control_sql, control_params = compile_cohort(instance_id, control_definition)
        outcome = outcome.lower().strip()
        relation,event_column=self.event_relation,self.event_column
        sql = f"""
            WITH groups AS (
                SELECT u.user_id, 'exposed' group_name FROM v_users_enriched u WHERE {exposed_sql}
                UNION ALL
                SELECT u.user_id, 'control' group_name FROM v_users_enriched u WHERE {control_sql}
            )
            SELECT group_name, count(DISTINCT g.user_id) AS users,
                   count(DISTINCT CASE WHEN e.user_id IS NOT NULL THEN g.user_id END) AS outcome_users,
                   count(DISTINCT CASE WHEN e.user_id IS NOT NULL THEN g.user_id END)::DOUBLE
                     / nullif(count(DISTINCT g.user_id), 0) AS outcome_rate
            FROM groups g LEFT JOIN {relation} e
              ON e.user_id = g.user_id AND e.instance_id = ? AND e.{event_column} = ?
            GROUP BY group_name ORDER BY group_name
        """
        return self.manager.execute_source(
            instance_id, sql, [*exposed_params, *control_params, instance_id, outcome],
            summary=f"exposed/control comparison for outcome {outcome}",
        )

    def materialize_cohort(
        self,
        run_id: str,
        system_name: str,
        hypothesis_id: str,
        cohort_definition: CohortDefinition | dict,
    ) -> QueryResult:
        definition = (
            cohort_definition if isinstance(cohort_definition, CohortDefinition)
            else CohortDefinition.model_validate(cohort_definition)
        )
        predicate, params = compile_cohort(definition.instance_id, definition)
        sql = f"SELECT DISTINCT u.user_id FROM v_users_enriched u WHERE {predicate} ORDER BY u.user_id"
        return self.manager.materialize_user_selection(
            run_id=run_id,
            system_name=system_name,
            hypothesis_id=hypothesis_id,
            instance_id=definition.instance_id,
            selection_sql=sql,
            parameters=params,
        )

    def get_debug_sample(
        self, instance_id: str, *, user_limit: int = 20, event_limit: int = 50
    ) -> QueryResult:
        """Return a deliberately small diagnostic sample, never an event dump."""
        if not 1 <= user_limit <= 20:
            raise GuardrailError("debug user_limit must be between 1 and 20")
        if not 1 <= event_limit <= 50:
            raise GuardrailError("debug event_limit must be between 1 and 50")
        sql = """
            WITH sampled_users AS (
                SELECT instance_id, user_id FROM v_users WHERE instance_id = ?
                ORDER BY user_id LIMIT ?
            )
            SELECT e.user_id, e.session_id, e.event_ts, e.raw_event_name,
                   e.screen, e.latency_ms, e.is_crash, e.payment_method
            FROM v_events e JOIN sampled_users s USING (instance_id, user_id)
            WHERE e.instance_id = ?
            ORDER BY e.user_id, e.event_ts
            LIMIT ?
        """
        return self.manager.execute_source(
            instance_id, sql, [instance_id, user_limit, instance_id, event_limit],
            summary=f"bounded debug sample: <= {user_limit} users, <= {event_limit} events",
            max_rows=50,
        )


def _steps(values: Sequence[str]) -> list[str]:
    steps = [value.lower().strip() for value in values if value and value.strip()]
    if not steps:
        raise GuardrailError("at least one event is required")
    if len(steps) != len(set(steps)):
        raise GuardrailError("event steps must be unique")
    return steps


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _dimension_expr(dimension: str, event_alias: str = "e") -> str:
    return f"{event_alias}.{dimension}" if dimension in {"payment_method", "screen"} else f"u.{dimension}"


def _metric_sql(
    metric: str, dimension: str, predicate: str, instance_id: str, minimum_users: int,
    relation: str = "v_events", event_column: str = "event_name", screen: str | None = None,
) -> tuple[str, list[object]]:
    dim = _dimension_expr(dimension)
    if metric in {"users", "crash_rate", "latency_p50", "latency_p95"}:
        value = {
            "users": "count(DISTINCT e.user_id)::DOUBLE",
            "crash_rate": "count(DISTINCT CASE WHEN e.is_crash THEN e.user_id END)::DOUBLE / nullif(count(DISTINCT e.user_id), 0)",
            "latency_p50": "quantile_cont(e.latency_ms, 0.50)",
            "latency_p95": "quantile_cont(e.latency_ms, 0.95)",
        }[metric]
        latency_filter = "AND e.latency_ms IS NOT NULL" if metric.startswith("latency") else ""
        bands = """
            , count(*) FILTER (WHERE e.latency_ms < 500) AS latency_below_500
            , count(*) FILTER (WHERE e.latency_ms >= 500 AND e.latency_ms < 1000) AS latency_500_999
            , count(*) FILTER (WHERE e.latency_ms >= 1000 AND e.latency_ms < 2000) AS latency_1000_1999
            , count(*) FILTER (WHERE e.latency_ms >= 2000 AND e.latency_ms < 4000) AS latency_2000_3999
            , count(*) FILTER (WHERE e.latency_ms >= 4000) AS latency_4000_plus
        """ if metric.startswith("latency") else ""
        numerator = ", count(DISTINCT CASE WHEN e.is_crash THEN e.user_id END) AS numerator_users" if metric == "crash_rate" else ""
        screen_filter = "AND e.screen = ?" if screen else ""
        trailing_params: list[object] = [instance_id]
        if screen: trailing_params.append(screen.lower().strip())
        trailing_params.append(minimum_users)
        return f"""
            SELECT {dim} AS dimension_value, count(DISTINCT e.user_id) AS exposed_users,
                   {value} AS metric_value {numerator} {bands}
            FROM {relation} e JOIN v_users_enriched u
              ON u.instance_id = e.instance_id AND u.user_id = e.user_id
            WHERE {predicate} AND e.instance_id = ? {screen_filter} {latency_filter}
            GROUP BY {dim} HAVING count(DISTINCT e.user_id) >= ?
            ORDER BY dimension_value
        """, trailing_params

    start_event = "checkout_start" if metric.startswith("checkout") else "payment_submit"
    numerator_condition = "has_crash" if metric == "checkout_crash_rate" else "completed"
    event_dim = dimension in {"payment_method", "screen"}
    dim_select = f"s.{dimension}" if event_dim else f"u.{dimension}"
    return f"""
        WITH starts AS (
            SELECT e.user_id, e.session_id, min(e.event_ts) AS start_at,
                   any_value(e.screen) AS screen, any_value(e.payment_method) AS payment_method
            FROM {relation} e JOIN v_users_enriched u
              ON u.instance_id = e.instance_id AND u.user_id = e.user_id
            WHERE {predicate} AND e.instance_id = ? AND e.{event_column} = ?
            GROUP BY e.user_id, e.session_id
        ), windows AS (
            SELECT s.*,
                   bool_or(e.{event_column} = 'order_confirmed' AND e.event_ts >= s.start_at) AS completed,
                   bool_or(e.is_crash AND e.event_ts >= s.start_at AND
                     (o.order_at IS NULL OR e.event_ts < o.order_at)) AS has_crash
            FROM starts s
            LEFT JOIN LATERAL (
                SELECT min(x.event_ts) order_at FROM {relation} x
                WHERE x.instance_id = ? AND x.user_id = s.user_id
                  AND x.session_id = s.session_id AND x.{event_column} = 'order_confirmed'
                  AND x.event_ts >= s.start_at
            ) o ON true
            LEFT JOIN {relation} e ON e.instance_id = ? AND e.user_id = s.user_id
              AND e.session_id = s.session_id AND e.event_ts >= s.start_at
            GROUP BY s.user_id, s.session_id, s.start_at, s.screen, s.payment_method, o.order_at
        )
        SELECT {dim_select} AS dimension_value, count(DISTINCT s.user_id) AS exposed_users,
               count(DISTINCT CASE WHEN {numerator_condition} THEN s.user_id END) AS numerator_users,
               count(DISTINCT CASE WHEN {numerator_condition} THEN s.user_id END)::DOUBLE
                 / nullif(count(DISTINCT s.user_id), 0) AS metric_value
        FROM windows s JOIN v_users_enriched u ON u.instance_id = ? AND u.user_id = s.user_id
        GROUP BY {dim_select} HAVING count(DISTINCT s.user_id) >= ?
        ORDER BY dimension_value
    """, [instance_id, start_event, instance_id, instance_id, instance_id, minimum_users]
