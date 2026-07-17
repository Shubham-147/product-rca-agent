"""JSON-only FastAPI entrypoint for executing the RCA application pipeline."""

from __future__ import annotations

import json
import time
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from openai import OpenAIError
from pydantic import BaseModel, Field
from pydantic_ai.exceptions import AgentRunError

from scripts.run_system_b import offline_react_model
from src.eval.harness import run_evaluation
from src.eval.judge import JudgeScore, judge_answer
from src.generator.events import DEFAULT_SEED, DEFAULT_USERS, generate_stub_data
from src.retrieval.db import DEFAULT_DB_PATH, DEFAULT_CSV_PATH, load_events
from src.systems.llm_client import FakeLLMClient, OpenAIClient
from src.systems.schema import Hypothesis
from src.systems.system_a import SystemA
from src.systems.system_b import SystemB
from src.systems.system_c import SystemC

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
_setup_lock = Lock()


class SystemName(str, Enum):
    A = "a"
    B = "b"
    C = "c"


class ExecutionMode(str, Enum):
    OFFLINE = "offline"
    OPENAI = "openai"


class SystemResult(BaseModel):
    system: str
    hypothesis: Hypothesis | None = None
    ruled_out_reason: str | None = None
    grounded_in_query_results: bool
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    state_trace: list[dict[str, Any]] = Field(default_factory=list)
    judge: JudgeScore | None = None
    latency_seconds: float = Field(ge=0.0)


class ExecutionResponse(BaseModel):
    symptom: str
    mode: ExecutionMode
    setup: dict[str, Any]
    results: list[SystemResult]
    evaluation: list[dict[str, Any]] | None = None
    total_latency_seconds: float = Field(ge=0.0)


app = FastAPI(
    title="Product Discovery Copilot API",
    description=(
        "Execute the stub-data RCA pipeline and receive structured JSON results. "
        "Use /docs for Swagger. Offline mode makes no paid API calls."
    ),
    version="0.1.0",
)


def _ensure_data(regenerate_data: bool) -> dict[str, Any]:
    required = [
        DATA_DIR / "taxonomy.json",
        DEFAULT_CSV_PATH,
        DATA_DIR / "manifest.json",
    ]
    generated = regenerate_data or not all(path.is_file() for path in required)
    database_built = generated or not DEFAULT_DB_PATH.is_file()
    with _setup_lock:
        generation_summary = None
        if generated:
            generation_summary = generate_stub_data(
                DATA_DIR, seed=DEFAULT_SEED, user_count=DEFAULT_USERS
            )
        loaded_rows = load_events() if database_built else None
    return {
        "data_regenerated": generated,
        "database_rebuilt": database_built,
        "generated_event_rows": (
            generation_summary["event_rows"] if generation_summary else None
        ),
        "database_rows_loaded": loaded_rows,
        "data_directory": str(DATA_DIR),
    }


def _offline_system_a() -> SystemA:
    response = json.dumps(
        {
            "mechanism": (
                "Retrieved taxonomy evidence suggests a plausible event-stream failure, "
                "but System A cannot validate it with aggregation."
            ),
            "affected_cohort": "Users described by the symptom; not SQL-derived",
            "evidence": ["Hybrid taxonomy retrieval context only"],
            "confounders_ruled_out": [],
            "confidence": 0.35,
        }
    )
    return SystemA(FakeLLMClient(default_response=response))


def _run_system(
    name: SystemName,
    symptom: str,
    mode: ExecutionMode,
    max_iterations: int,
) -> SystemResult:
    started = time.perf_counter()
    if name == SystemName.A:
        system = _offline_system_a() if mode == ExecutionMode.OFFLINE else SystemA(OpenAIClient())
        hypothesis = system.analyze(symptom)
        return SystemResult(
            system="System A",
            hypothesis=hypothesis,
            grounded_in_query_results=False,
            latency_seconds=time.perf_counter() - started,
        )

    if name == SystemName.B:
        model = offline_react_model(symptom) if mode == ExecutionMode.OFFLINE else None
        system = SystemB(model=model)
        hypothesis = system.analyze(symptom)
        sql_called = any(
            call["tool"] == "run_sql" and call.get("success", True)
            for call in system.deps.tool_calls
        )
        return SystemResult(
            system="System B",
            hypothesis=hypothesis,
            grounded_in_query_results=sql_called and bool(hypothesis.affected_cohort),
            tool_calls=system.deps.tool_calls,
            latency_seconds=time.perf_counter() - started,
        )

    system = SystemC(max_iterations=max_iterations)
    graph_result = system.run(symptom)
    return SystemResult(
        system="System C",
        hypothesis=graph_result.final_hypothesis,
        ruled_out_reason=graph_result.ruled_out_reason,
        grounded_in_query_results=(
            graph_result.final_hypothesis is not None
            and bool(graph_result.final_hypothesis.affected_cohort)
        ),
        state_trace=graph_result.state_trace,
        latency_seconds=time.perf_counter() - started,
    )


def _attach_judges(
    results: list[SystemResult], symptom: str, mode: ExecutionMode
) -> None:
    if mode == ExecutionMode.OPENAI:
        client = OpenAIClient()
    else:
        client = FakeLLMClient(
            default_response=json.dumps(
                {
                    "score": 4,
                    "rationale": (
                        "The narrative is tied to its cited evidence, while unresolved "
                        "factors remain visible in the structured hypothesis."
                    ),
                }
            )
        )
    for result in results:
        if result.hypothesis is not None:
            result.judge = judge_answer(client, symptom, result.hypothesis)


def execute_pipeline(
    symptom: str,
    systems: list[SystemName],
    mode: ExecutionMode,
    regenerate_data: bool,
    include_evaluation: bool,
    include_judge: bool,
    max_iterations: int,
) -> ExecutionResponse:
    started = time.perf_counter()
    try:
        setup = _ensure_data(regenerate_data)
        results = [
            _run_system(name, symptom, mode, max_iterations) for name in systems
        ]
        if include_judge:
            _attach_judges(results, symptom, mode)
        evaluation = None
        if include_evaluation:
            frame = run_evaluation(DATA_DIR / "eval_results.csv")
            evaluation = json.loads(frame.to_json(orient="records"))
        return ExecutionResponse(
            symptom=symptom,
            mode=mode,
            setup=setup,
            results=results,
            evaluation=evaluation,
            total_latency_seconds=time.perf_counter() - started,
        )
    except AgentRunError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"The agent could not produce a valid grounded result: {exc}",
        ) from exc
    except OpenAIError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI request failed: {exc}",
        ) from exc
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    """Return a minimal liveness response."""
    return {"status": "ok"}


@app.post("/execute", response_model=ExecutionResponse, tags=["pipeline"])
def execute(
    symptom: str = Query(
        ...,
        min_length=3,
        description="Product symptom or root-cause question to investigate.",
        examples=["Why did checkout abandonment spike?"],
    ),
    systems: list[SystemName] = Query(
        default=[SystemName.A, SystemName.B, SystemName.C],
        description="Systems to run. Repeat this query parameter to select several.",
    ),
    mode: ExecutionMode = Query(
        default=ExecutionMode.OFFLINE,
        description="Offline uses deterministic test models; openai uses .env credentials.",
    ),
    regenerate_data: bool = Query(
        default=False,
        description="Regenerate taxonomy/events and rebuild DuckDB before execution.",
    ),
    include_evaluation: bool = Query(
        default=False,
        description="Also run the complete blinded comparative evaluation harness.",
    ),
    include_judge: bool = Query(
        default=False,
        description="Attach a 1–5 evidence-faithfulness score to each hypothesis.",
    ),
    max_iterations: int = Query(
        default=3,
        ge=0,
        le=10,
        description="Maximum System C falsifier revisions.",
    ),
) -> ExecutionResponse:
    """Execute selected systems for one symptom and return structured JSON."""
    if not systems:
        raise HTTPException(status_code=422, detail="Select at least one system.")
    return execute_pipeline(
        symptom=symptom,
        systems=systems,
        mode=mode,
        regenerate_data=regenerate_data,
        include_evaluation=include_evaluation,
        include_judge=include_judge,
        max_iterations=max_iterations,
    )


@app.post("/execute/full", response_model=ExecutionResponse, tags=["pipeline"])
def execute_full(
    symptom: str = Query(
        ...,
        min_length=3,
        description="Product symptom or root-cause question to investigate.",
        examples=["Why are older Android users crashing before adding to cart?"],
    ),
    mode: ExecutionMode = Query(default=ExecutionMode.OFFLINE),
    regenerate_data: bool = Query(default=False),
    max_iterations: int = Query(default=3, ge=0, le=10),
) -> ExecutionResponse:
    """Run A/B/C, comparative evaluation, and qualitative judging in one request."""
    return execute_pipeline(
        symptom=symptom,
        systems=[SystemName.A, SystemName.B, SystemName.C],
        mode=mode,
        regenerate_data=regenerate_data,
        include_evaluation=True,
        include_judge=True,
        max_iterations=max_iterations,
    )
