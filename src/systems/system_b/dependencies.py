"""Injected, per-run dependencies and observable state for System B."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from src.analytics import DeterministicAnalytics
from src.database import DuckDBManager, QueryResult
from src.guardrails import SafeAuditLogger, SystemBToolGuard
from src.retrieval import CanonicalEventResolver, HybridRetriever
from src.retrieval.schemas import EventResolution


@dataclass
class QueryCache:
    values: dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemBDependencies:
    analytics: DeterministicAnalytics
    retriever: HybridRetriever
    event_resolver: CanonicalEventResolver
    cohort_materializer: Callable[..., QueryResult]
    safe_query_executor: DuckDBManager
    query_cache: QueryCache
    run_logger: SafeAuditLogger
    guardrail_service: SystemBToolGuard
    run_id: str
    instance_id: str
    query_results: dict[str, QueryResult] = field(default_factory=dict)
    source_chunks: set[str] = field(default_factory=set)
    event_resolutions: dict[str, EventResolution] = field(default_factory=dict)
    materialized_hypotheses: set[str] = field(default_factory=set)
    tool_events: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Expose the shared guard's cache through the explicitly injected cache
        # dependency; there is one source of truth for duplicate tool calls.
        self.query_cache.values = self.guardrail_service.cache

    def remember_query(self, result: QueryResult) -> QueryResult:
        if result.row_count > 100 or len(result.rows) > 100:
            result = result.model_copy(update={"rows": result.rows[:100], "row_count": min(result.row_count, 100)})
        self.query_results[result.query_id] = result
        return result
