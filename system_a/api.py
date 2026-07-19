from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from .execution import run_cases_parallel
from .metrics import calculate_metrics


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts/system_a"

app = FastAPI(
    title="System A Vanilla RAG API",
    version="1.0.0",
    description="Run or reuse System A artifacts and return offline evaluation metrics.",
)


class MetricsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recalculate: bool = Field(
        default=False,
        description="true regenerates all predictions with external OpenAI calls; omitted or false uses available artifacts",
    )


class SelectedCasesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_ids: list[str] = Field(
        ...,
        min_length=1,
        description="One or more case IDs from data/warehouses/index.json",
    )


def _workers() -> int:
    workers = int(os.environ.get("SYSTEM_A_MAX_WORKERS", "4"))
    if not 1 <= workers <= 16:
        raise ValueError("SYSTEM_A_MAX_WORKERS must be between 1 and 16")
    return workers


def _available_ids() -> list[str]:
    return [row["instance_id"] for row in json.loads(
        (DATA_ROOT / "warehouses/index.json").read_text()
    )]


def _run(request: MetricsRequest) -> dict:
    workers = _workers()
    if request.recalculate:
        ids = _available_ids()
        run_cases_parallel(DATA_ROOT, ids, ARTIFACT_ROOT, max_workers=workers)
    report = calculate_metrics(DATA_ROOT, ARTIFACT_ROOT)
    return {"recalculated": request.recalculate, "parallel_workers": workers, **report}


def _run_selected(request: SelectedCasesRequest) -> dict:
    requested = list(dict.fromkeys(request.instance_ids))
    available = set(_available_ids())
    unsupported = [iid for iid in requested if iid not in available]
    if unsupported:
        raise ValueError(f"Unsupported instance IDs: {unsupported}")
    workers = min(_workers(), len(requested))
    results = run_cases_parallel(DATA_ROOT, requested, ARTIFACT_ROOT, max_workers=workers)
    return {
        "executed": len(results),
        "instance_ids": requested,
        "parallel_workers": workers,
        "results": [
            {
                "instance_id": result["prediction"].instance_id,
                "prediction": result["prediction"].model_dump(),
                "prediction_path": str(result["prediction_path"]),
                "trace_path": str(result["trace_path"]),
                "timing": result["trace"]["timing"],
            }
            for result in results
        ],
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "system": "A"}


@app.post("/system-a/metrics")
async def system_a_metrics(request: MetricsRequest) -> dict:
    try:
        return await run_in_threadpool(_run, request)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/system-a/run-selected")
async def system_a_run_selected(request: SelectedCasesRequest) -> dict:
    try:
        return await run_in_threadpool(_run_selected, request)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
