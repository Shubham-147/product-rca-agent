"""System B: Pydantic AI ReAct agent with retrieval, resolution, and SQL tools."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import duckdb
from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from src.config import get_settings
from src.retrieval.bm25 import BM25Retriever
from src.retrieval.db import run_sql as query_duckdb
from src.retrieval.hybrid import resolve_events as hybrid_resolve_events
from src.systems.schema import Hypothesis

RetrieveFn = Callable[[str], list[dict[str, Any]]]
ResolveFn = Callable[[str], list[dict[str, Any]]]
SqlFn = Callable[[str], pd.DataFrame]


def retrieve(query: str) -> list[dict[str, Any]]:
    """Retrieve stub specification chunks from taxonomy descriptions.

    The stub has no separate PRD corpus yet, so taxonomy descriptions serve as the
    Phase-1 stand-in spec chunks.
    """
    return [hit.model_dump() for hit in BM25Retriever().search(query, k=5)]


def resolve_events(query: str) -> list[dict[str, Any]]:
    """Resolve free text to event taxonomy candidates through the hybrid retriever."""
    return [hit.model_dump() for hit in hybrid_resolve_events(query, k=5)]


def run_sql(query: str) -> pd.DataFrame:
    """Execute SQL against the embedded event database."""
    return query_duckdb(query)


@dataclass
class SystemBDeps:
    """Injected tool implementations and an auditable call trace."""

    retrieve_fn: RetrieveFn = retrieve
    resolve_fn: ResolveFn = resolve_events
    sql_fn: SqlFn = run_sql
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


def _retrieve_tool(ctx: RunContext[SystemBDeps], query: str) -> list[dict[str, Any]]:
    """Retrieve PRD/spec text chunks relevant to the symptom."""
    result = ctx.deps.retrieve_fn(query)
    ctx.deps.tool_calls.append({"tool": "retrieve", "query": query, "rows": len(result)})
    return result


def _resolve_events_tool(
    ctx: RunContext[SystemBDeps], query: str
) -> list[dict[str, Any]]:
    """Resolve messy event language to known taxonomy event names."""
    result = ctx.deps.resolve_fn(query)
    ctx.deps.tool_calls.append(
        {
            "tool": "resolve_events",
            "query": query,
            "rows": len(result),
            "event_names": [row["event_name"] for row in result],
        }
    )
    return result


def _run_sql_tool(ctx: RunContext[SystemBDeps], query: str) -> list[dict[str, Any]]:
    """Run DuckDB SQL, returning schema feedback on invalid queries so they can be retried."""
    try:
        frame = ctx.deps.sql_fn(query)
    except duckdb.Error as exc:
        error = str(exc)
        ctx.deps.tool_calls.append(
            {
                "tool": "run_sql",
                "query": query,
                "rows": 0,
                "success": False,
                "error": error,
            }
        )
        return [
            {
                "error": error,
                "instruction": "Correct the SQL and call run_sql again.",
                "available_columns": [
                    "user_id",
                    "session_id",
                    "timestamp",
                    "event_name",
                    "screen",
                    "category",
                    "device_tier",
                    "os",
                    "cold_start",
                    "latency_ms",
                    "payment_provider",
                    "outcome",
                ],
            }
        ]
    records = json.loads(frame.to_json(orient="records", date_format="iso"))
    ctx.deps.tool_calls.append(
        {
            "tool": "run_sql",
            "query": query,
            "rows": len(records),
            "success": True,
        }
    )
    return records


INSTRUCTIONS = """You are System B, a ReAct root-cause analyst.
Reason about the symptom, call retrieve and resolve_events for context, then call run_sql
to compute the actually affected users or cohort. Repeat tools if needed. Never invent
user IDs. Your final Hypothesis must cite SQL observations in evidence, use a non-empty
affected_cohort grounded in those results, and list only confounders genuinely tested.

The DuckDB table is named events and has exactly these columns:
user_id VARCHAR, session_id VARCHAR, timestamp TIMESTAMPTZ, event_name VARCHAR,
screen VARCHAR, category VARCHAR, device_tier VARCHAR, os VARCHAR, cold_start BOOLEAN,
latency_ms BIGINT, payment_provider VARCHAR, outcome VARCHAR.
The timestamp column is named timestamp, not event_ts. Use only listed columns. If run_sql
returns an error, inspect its available_columns, correct the query, and call run_sql again
before producing the final Hypothesis.
"""


def build_openai_model() -> OpenAIModel:
    """Build Pydantic AI's OpenAI model using only centralized settings."""
    settings = get_settings()
    provider = OpenAIProvider(api_key=settings.openai_api_key)
    return OpenAIModel(settings.openai_model, provider=provider)


def build_agent(model: Model | None = None) -> Agent[SystemBDeps, Hypothesis]:
    """Build the typed Pydantic AI agent and register its three ReAct tools."""
    return Agent(
        model or build_openai_model(),
        deps_type=SystemBDeps,
        output_type=Hypothesis,
        instructions=INSTRUCTIONS,
        tools=[_retrieve_tool, _resolve_events_tool, _run_sql_tool],
        retries=2,
    )


class SystemB:
    """Synchronous facade over the typed Pydantic AI agent."""

    def __init__(self, model: Model | None = None, deps: SystemBDeps | None = None) -> None:
        self.deps = deps or SystemBDeps()
        self.agent = build_agent(model)

    def analyze(self, question: str) -> Hypothesis:
        """Run the ReAct loop and return Pydantic-validated output."""
        if not question.strip():
            raise ValueError("question must not be empty")
        result = self.agent.run_sync(question, deps=self.deps)
        return Hypothesis.model_validate(result.output)
