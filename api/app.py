"""Expose existing System A/B/C evaluation manifests to the UI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "eval" / "results"
SYSTEMS = ("A", "B", "C")


class SystemAggregate(BaseModel):
    model_config = ConfigDict(extra="allow")
    system: str
    model: str
    n: int
    errors: int
    top1_accuracy: float
    top1_accuracy_faultcases: float
    cohort_f1_mean_faultcases: float
    decoy_fp_rate_nofault: float
    total_tokens: int
    est_cost_usd: float
    mean_latency_s: float


class CaseResult(BaseModel):
    """Complete per-system case row from an evaluation manifest."""

    model_config = ConfigDict(extra="forbid")
    instance_id: str
    gold_fault: str
    has_fault: bool
    top_pred: str | None = None
    top1_correct: bool
    cohort_f1: float | None = None
    false_positive: bool
    recall_at_3: bool
    top_cohort: str | None = None
    tokens: int
    input_tokens: int
    output_tokens: int
    latency_s: float
    n_tool_calls: int
    error: str | None = None


class ComparisonCase(BaseModel):
    instance_id: str
    gold_fault: str
    has_fault: bool
    systems: dict[str, CaseResult]


class ComparisonResponse(BaseModel):
    aggregates: list[SystemAggregate]
    cases: list[ComparisonCase]


def _load_manifest(system: str) -> dict[str, Any]:
    path = RESULTS_DIR / f"suite_system_{system}.json"
    if not path.is_file():
        raise HTTPException(status_code=503, detail=f"Missing comparison data: {path.name}")
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Invalid {path.name}: {exc}") from exc
    if not isinstance(data.get("aggregate"), dict) or not isinstance(data.get("cases"), list):
        raise HTTPException(status_code=500, detail=f"Invalid manifest shape: {path.name}")
    return data


def load_comparison() -> ComparisonResponse:
    """Read and align the saved manifests; never run models or mutate results."""
    manifests = {system: _load_manifest(system) for system in SYSTEMS}
    aggregates = [
        SystemAggregate(
            system=system,
            model=manifest.get("model", "unknown"),
            **manifest["aggregate"],
        )
        for system, manifest in manifests.items()
    ]
    indexed = {
        system: {case["instance_id"]: case for case in manifest["cases"]}
        for system, manifest in manifests.items()
    }
    case_ids = sorted(set().union(*(set(cases) for cases in indexed.values())))
    cases: list[ComparisonCase] = []
    for instance_id in case_ids:
        missing = [system for system in SYSTEMS if instance_id not in indexed[system]]
        if missing:
            raise HTTPException(
                status_code=409,
                detail=f"{instance_id} missing from System(s): {', '.join(missing)}",
            )
        source = indexed["A"][instance_id]
        cases.append(ComparisonCase(
            instance_id=instance_id,
            gold_fault=source["gold_fault"],
            has_fault=bool(source["has_fault"]),
            systems={
                system: CaseResult.model_validate(indexed[system][instance_id])
                for system in SYSTEMS
            },
        ))
    return ComparisonResponse(aggregates=aggregates, cases=cases)


app = FastAPI(
    title="Product RCA Comparison API",
    version="1.0.0",
    description="Read-only A/B/C benchmark comparison data for the UI.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
origins = [item.strip() for item in os.environ.get(
    "COMPARISON_UI_ORIGINS", "http://localhost:3000,http://localhost:5173"
).split(",") if item.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/comparison", response_model=ComparisonResponse)
def comparison() -> ComparisonResponse:
    """Return aggregate metrics and case-aligned A/B/C results."""
    return load_comparison()
