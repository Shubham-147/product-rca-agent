"""Lazy source/runtime DuckDB connection management and query logging."""

from __future__ import annotations

import json
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import duckdb

from src.config import AppSettings, get_settings
from src.guardrails import GuardrailError, validate_fallback_query, validate_source_query

from .models import QueryResult
from .views import create_normalized_views, create_resolved_events_view
from src.retrieval.schemas import AliasMapping


class DuckDBManager:
    """Own source and runtime database lifecycles without import-time I/O."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        self._settings = settings
        self._runtime_initialized = False
        self._init_lock = threading.Lock()
        self._alias_mappings: list[AliasMapping] = []

    def set_alias_mappings(self, mappings: list[AliasMapping]) -> None:
        self._alias_mappings = list(mappings)

    @property
    def has_resolved_events(self) -> bool:
        return bool(self._alias_mappings)

    @property
    def settings(self) -> AppSettings:
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    @contextmanager
    def _source_connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        path = self.settings.source_duckdb_path
        if not path.is_file():
            raise FileNotFoundError(f"source DuckDB does not exist: {path}")
        connection = duckdb.connect(str(path), read_only=True)
        try:
            create_normalized_views(connection)
            if self._alias_mappings:
                create_resolved_events_view(connection, self._alias_mappings)
            yield connection
        finally:
            connection.close()

    @contextmanager
    def runtime_connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        self.initialize_runtime()
        connection = duckdb.connect(str(self.settings.runtime_duckdb_path))
        try:
            yield connection
        finally:
            connection.close()

    def initialize_runtime(self) -> None:
        if self._runtime_initialized:
            return
        with self._init_lock:
            if self._runtime_initialized:
                return
            path = self.settings.runtime_duckdb_path
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = duckdb.connect(str(path))
            try:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS run_logs (
                        run_id VARCHAR PRIMARY KEY,
                        system_name VARCHAR NOT NULL,
                        instance_id VARCHAR NOT NULL,
                        started_at TIMESTAMP NOT NULL,
                        completed_at TIMESTAMP,
                        status VARCHAR NOT NULL,
                        metadata_json VARCHAR
                    )
                """)
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS query_logs (
                        query_id VARCHAR PRIMARY KEY,
                        instance_id VARCHAR NOT NULL,
                        executed_sql VARCHAR NOT NULL,
                        parameters_json VARCHAR NOT NULL,
                        duration_ms DOUBLE NOT NULL,
                        row_count BIGINT NOT NULL,
                        result_summary VARCHAR NOT NULL,
                        created_at TIMESTAMP DEFAULT current_timestamp
                    )
                """)
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS aggregate_cache (
                        cache_key VARCHAR PRIMARY KEY,
                        instance_id VARCHAR NOT NULL,
                        query_id VARCHAR NOT NULL,
                        result_json VARCHAR NOT NULL,
                        created_at TIMESTAMP DEFAULT current_timestamp
                    )
                """)
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS predicted_cohorts (
                        run_id VARCHAR NOT NULL,
                        system_name VARCHAR NOT NULL,
                        hypothesis_id VARCHAR NOT NULL,
                        instance_id VARCHAR NOT NULL,
                        user_id VARCHAR NOT NULL,
                        materialized_at TIMESTAMP DEFAULT current_timestamp,
                        PRIMARY KEY (run_id, system_name, hypothesis_id, instance_id, user_id)
                    )
                """)
            finally:
                connection.close()
            self._runtime_initialized = True

    def execute_source(
        self,
        instance_id: str,
        sql: str,
        parameters: list[Any] | None = None,
        *,
        summary: str,
        max_rows: int | None = None,
    ) -> QueryResult:
        if not instance_id or not instance_id.strip():
            raise GuardrailError("instance_id is required")
        params = list(parameters or [])
        validate_source_query(sql, instance_id)
        if instance_id not in params:
            raise GuardrailError("bound parameters must include instance_id")
        query_id = f"qry_{uuid.uuid4().hex}"
        started = time.perf_counter()
        rows: list[dict[str, Any]] = []
        with self._source_connection() as connection:
            timer = threading.Timer(self.settings.query_timeout_seconds, connection.interrupt)
            timer.daemon = True
            timer.start()
            try:
                cursor = connection.execute(sql, params)
                columns = [item[0] for item in cursor.description]
                fetched = cursor.fetchall()
            finally:
                timer.cancel()
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        limit = max_rows if max_rows is not None else self.settings.sql_result_row_limit
        if len(fetched) > limit:
            raise GuardrailError(f"query returned {len(fetched)} rows; limit is {limit}")
        rows = [dict(zip(columns, row)) for row in fetched]
        result = QueryResult(
            query_id=query_id,
            executed_sql=sql.strip(),
            parameters=params,
            duration_ms=duration_ms,
            row_count=len(rows),
            result_summary=summary,
            rows=rows,
        )
        self._log_query(instance_id, result)
        return result

    def execute_source_write_forbidden(self, sql: str) -> None:
        """Explicit guarded entry point used to demonstrate source immutability."""
        validate_source_query(sql)
        raise GuardrailError("source database writes are forbidden")

    def execute_fallback_sql(
        self, instance_id: str, sql: str, parameters: list[Any] | None = None
    ) -> QueryResult:
        params = list(parameters or [])
        validate_fallback_query(sql, instance_id, self.settings.sql_result_row_limit)
        if instance_id not in params:
            raise GuardrailError("fallback SQL must bind the requested instance_id")
        return self.execute_source(
            instance_id, sql, params, summary="explicit guarded fallback SQL"
        )

    def list_exposed_source_relations(self) -> list[str]:
        """Return the fixed public relations, never source catalog contents."""
        return ["events", "users", "v_events", "v_users", "v_users_enriched"]

    def record_run(
        self,
        *,
        run_id: str,
        system_name: str,
        instance_id: str,
        started_at: Any,
        status: str,
        completed_at: Any = None,
        metadata: dict[str, Any] | None = None,
        validated: bool = False,
    ) -> None:
        if status.lower() in {"completed", "success", "successful"} and not validated:
            raise GuardrailError("successful runs require a validated report")
        with self.runtime_connection() as connection:
            connection.execute("""
                INSERT OR REPLACE INTO run_logs
                (run_id, system_name, instance_id, started_at, completed_at, status, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [run_id, system_name, instance_id, started_at, completed_at, status,
                    json.dumps(metadata or {}, default=str)])

    def cache_aggregate(self, cache_key: str, instance_id: str, result: QueryResult) -> None:
        with self.runtime_connection() as connection:
            connection.execute("""
                INSERT OR REPLACE INTO aggregate_cache
                (cache_key, instance_id, query_id, result_json, created_at)
                VALUES (?, ?, ?, ?, current_timestamp)
            """, [cache_key, instance_id, result.query_id, result.model_dump_json()])

    def get_cached_aggregate(self, cache_key: str, instance_id: str) -> QueryResult | None:
        with self.runtime_connection() as connection:
            row = connection.execute(
                "SELECT result_json FROM aggregate_cache WHERE cache_key = ? AND instance_id = ?",
                [cache_key, instance_id],
            ).fetchone()
        return QueryResult.model_validate_json(row[0]) if row else None

    def materialize_user_selection(
        self,
        *,
        run_id: str,
        system_name: str,
        hypothesis_id: str,
        instance_id: str,
        selection_sql: str,
        parameters: list[Any],
    ) -> QueryResult:
        """Persist a guarded user selection while returning only an aggregate count."""
        validate_source_query(selection_sql, instance_id)
        if instance_id not in parameters:
            raise GuardrailError("cohort materialization must bind its instance_id")
        query_id = f"qry_{uuid.uuid4().hex}"
        started = time.perf_counter()
        with self._source_connection() as source:
            user_ids = [row[0] for row in source.execute(selection_sql, parameters).fetchall()]
        with self.runtime_connection() as runtime:
            runtime.execute(
                "DELETE FROM predicted_cohorts WHERE run_id = ? AND system_name = ? "
                "AND hypothesis_id = ? AND instance_id = ?",
                [run_id, system_name, hypothesis_id, instance_id],
            )
            if user_ids:
                runtime.executemany(
                    """INSERT INTO predicted_cohorts
                       (run_id, system_name, hypothesis_id, instance_id, user_id)
                       VALUES (?, ?, ?, ?, ?)""",
                    [(run_id, system_name, hypothesis_id, instance_id, uid) for uid in user_ids],
                )
        result = QueryResult(
            query_id=query_id,
            executed_sql=selection_sql.strip(),
            parameters=list(parameters),
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            row_count=1,
            result_summary=f"materialized {len(user_ids)} users",
            rows=[{"materialized_users": len(user_ids)}],
        )
        self._log_query(instance_id, result)
        return result

    def _log_query(self, instance_id: str, result: QueryResult) -> None:
        with self.runtime_connection() as connection:
            connection.execute(
                """INSERT INTO query_logs VALUES (?, ?, ?, ?, ?, ?, ?, current_timestamp)""",
                [
                    result.query_id,
                    instance_id,
                    result.executed_sql,
                    json.dumps(result.parameters, default=str),
                    result.duration_ms,
                    result.row_count,
                    result.result_summary,
                ],
            )


_manager: DuckDBManager | None = None
_manager_lock = threading.Lock()


def get_duckdb_manager() -> DuckDBManager:
    """Create the process manager on first use; no connections are opened here."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = DuckDBManager()
    return _manager


def clear_duckdb_manager() -> None:
    global _manager
    with _manager_lock:
        _manager = None
