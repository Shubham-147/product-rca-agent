"""Connection-local normalized views over the source benchmark tables."""

from __future__ import annotations

import duckdb
from src.retrieval.schemas import AliasMapping


def create_normalized_views(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute("""
        CREATE OR REPLACE TEMP VIEW v_events AS
        SELECT
            trim(CAST(user_id AS VARCHAR)) AS user_id,
            nullif(trim(CAST(session_id AS VARCHAR)), '') AS session_id,
            try_cast(event_ts AS TIMESTAMP) AS event_ts,
            CAST(event_name AS VARCHAR) AS raw_event_name,
            lower(trim(CAST(event_name AS VARCHAR))) AS event_name,
            lower(nullif(trim(CAST(screen AS VARCHAR)), '')) AS screen,
            lower(nullif(trim(CAST(os AS VARCHAR)), '')) AS os,
            lower(nullif(trim(CAST(device_type AS VARCHAR)), '')) AS device_type,
            try_cast(device_age_months AS BIGINT) AS device_age_months,
            lower(nullif(trim(CAST(geo AS VARCHAR)), '')) AS geo,
            lower(nullif(trim(CAST(channel AS VARCHAR)), '')) AS channel,
            coalesce(try_cast(is_returning AS BOOLEAN), false) AS is_returning,
            try_cast(latency_ms AS DOUBLE) AS latency_ms,
            coalesce(try_cast(is_crash AS BOOLEAN), false) AS is_crash,
            lower(nullif(trim(CAST(payment_method AS VARCHAR)), '')) AS payment_method,
            trim(CAST(instance_id AS VARCHAR)) AS instance_id
        FROM events
        WHERE nullif(trim(CAST(instance_id AS VARCHAR)), '') IS NOT NULL
          AND nullif(trim(CAST(user_id AS VARCHAR)), '') IS NOT NULL
    """)
    connection.execute("""
        CREATE OR REPLACE TEMP VIEW v_users AS
        SELECT
            trim(CAST(user_id AS VARCHAR)) AS user_id,
            lower(nullif(trim(CAST(os AS VARCHAR)), '')) AS os,
            lower(nullif(trim(CAST(device_type AS VARCHAR)), '')) AS device_type,
            try_cast(device_age_months AS BIGINT) AS device_age_months,
            lower(nullif(trim(CAST(geo AS VARCHAR)), '')) AS geo,
            lower(nullif(trim(CAST(channel AS VARCHAR)), '')) AS channel,
            coalesce(try_cast(is_returning AS BOOLEAN), false) AS is_returning,
            try_cast(acquired_ts AS TIMESTAMP) AS acquired_ts,
            trim(CAST(instance_id AS VARCHAR)) AS instance_id
        FROM users
        WHERE nullif(trim(CAST(instance_id AS VARCHAR)), '') IS NOT NULL
          AND nullif(trim(CAST(user_id AS VARCHAR)), '') IS NOT NULL
    """)
    connection.execute("""
        CREATE OR REPLACE TEMP VIEW v_users_enriched AS
        SELECT *, CASE
            WHEN device_age_months IS NULL OR device_age_months < 0 THEN 'unknown'
            WHEN device_age_months BETWEEN 0 AND 11 THEN '0-11 months'
            WHEN device_age_months BETWEEN 12 AND 23 THEN '12-23 months'
            WHEN device_age_months BETWEEN 24 AND 35 THEN '24-35 months'
            WHEN device_age_months BETWEEN 36 AND 47 THEN '36-47 months'
            ELSE '48+ months'
        END AS device_age_bucket
        FROM v_users
    """)


def create_resolved_events_view(connection: duckdb.DuckDBPyConnection, mappings: list[AliasMapping]) -> None:
    """Build a connection-local deterministic alias table and resolved event view."""
    connection.execute("DROP TABLE IF EXISTS temp_event_alias_mappings")
    connection.execute("""CREATE TEMP TABLE temp_event_alias_mappings(
        raw_event_name VARCHAR, normalized_alias VARCHAR, canonical_event VARCHAR,
        is_resolved BOOLEAN, funnel_step VARCHAR, is_expected_dropoff BOOLEAN,
        taxonomy_version VARCHAR)""")
    rows=[(m.raw_event_name,m.raw_event_name.lower().strip(),m.canonical_event,m.is_resolved,m.funnel_step,
           m.is_expected_dropoff,m.taxonomy_version) for m in sorted(mappings,key=lambda x:x.raw_event_name)]
    if rows: connection.executemany("INSERT INTO temp_event_alias_mappings VALUES (?,?,?,?,?,?,?)",rows)
    connection.execute("""CREATE OR REPLACE TEMP VIEW v_events_resolved AS
        SELECT e.*, m.canonical_event, coalesce(m.is_resolved,false) AS is_resolved,
               m.funnel_step, coalesce(m.is_expected_dropoff,false) AS is_expected_dropoff,
               m.taxonomy_version
        FROM v_events e LEFT JOIN temp_event_alias_mappings m ON e.event_name=m.normalized_alias""")
