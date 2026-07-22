"""System A — thin vanilla RAG over the foundation shared with B and C.

System A has no private pipeline and exposes no tools to its model. It performs one
fixed, deterministic evidence pass with the shared event resolver, analytics compiler,
warehouse, and spec retriever, followed by one structured generation call. Systems B
and C use the same foundation adaptively through tools; that orchestration difference
is the experiment.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from ..analytics import Analytics
from ..config import build_model, get_settings
from ..contracts import AgentHypothesis
from ..retrieval.spec import get_spec_index
from ..trace import TraceStep, extract_trace
from ..warehouse import Warehouse
from .base import RunResult, load_task


DIMENSIONS = ("os", "device_type", "geo", "channel", "is_returning")
METRICS = ("checkout_p95", "cold_start_p95", "crash_rate", "payment_error_rate")

INSTRUCTIONS = """\
You are System A, a vanilla-RAG product analyst. You receive one fixed evidence bundle
and must return the single best hypothesis. You have no tools and cannot request more
data. Use only supplied evidence; do not invent measurements. Identify the regressed
funnel step, the compatible mechanism, and the simplest concentrated cohort supported
by sample sizes. Use innocent_dropoff only when the bundle shows no actionable fault.
Every evidence claim must quote relevant pre/post values from the bundle. Return one
typed hypothesis with an allowed Cohort predicate.
"""


def build_evidence(task_path: str | Path) -> dict:
    """Build A's one-shot evidence using only shared deterministic foundations."""
    task_path = Path(task_path)
    task = load_task(task_path)
    with Warehouse.from_task(task_path) as warehouse:
        analytics = Analytics(warehouse)
        evidence = {
            "instance_id": task["instance_id"],
            "attribute_domains": analytics.attribute_domains(),
            "funnel_overall": [asdict(row) for row in analytics.funnel()],
            "funnel_by_dimension": {
                dim: [asdict(row) for row in analytics.funnel([dim])]
                for dim in DIMENSIONS
            },
            "metrics_by_dimension": {
                metric: {
                    dim: [asdict(row) for row in analytics.metric_by_segment(metric, [dim])]
                    for dim in DIMENSIONS
                }
                for metric in METRICS
            },
        }
    retrieval_query = (
        task["question"] + " checkout latency cold start crash payment failure "
        "dead screen funnel SLO optional step innocent dropoff"
    )
    evidence["retrieved_spec"] = [
        asdict(hit) for hit in get_spec_index().query(retrieval_query, k=8)
    ]
    return evidence


def build_generator(model=None) -> Agent[None, AgentHypothesis]:
    """One structured generator, deliberately without registered tools."""
    return Agent(model, output_type=AgentHypothesis, instructions=INSTRUCTIONS, retries=1)


class SystemA:
    name = "A"

    def __init__(self, model=None):
        self.settings = get_settings()
        self.model = model or build_model(self.settings)
        self.generator = build_generator(self.model)

    def run(self, task_path: str | Path, model=None) -> RunResult:
        task = load_task(task_path)
        iid = task["instance_id"]
        started = time.monotonic()
        run_model = model or self.model
        if run_model is None:
            raise RuntimeError(
                "No LLM model available. Set RCA_LLM_BASE_URL for real runs, or pass "
                "a stub model to SystemA/run()."
            )
        try:
            evidence = build_evidence(task_path)
            prompt = (
                task["question"] + "\n\nONE-SHOT SHARED EVIDENCE BUNDLE:\n" +
                json.dumps(evidence, default=str, separators=(",", ":"))
            )
            result = self.generator.run_sync(
                prompt,
                model=run_model,
                usage_limits=UsageLimits(
                    request_limit=2,
                    total_tokens_limit=self.settings.total_tokens_limit,
                ),
                model_settings={
                    "temperature": self.settings.temperature,
                    "timeout": self.settings.request_timeout_s,
                    "max_tokens": self.settings.max_output_tokens,
                },
            )
        except Exception as exc:
            return RunResult(
                system=self.name,
                instance_id=iid,
                hypotheses=[],
                error=f"{type(exc).__name__}: {exc}",
                latency_s=round(time.monotonic() - started, 1),
            )

        output = result.output
        usage = result.usage
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        trace = extract_trace(self.name, iid, self.settings.model_name, result.all_messages())
        trace.steps.insert(0, TraceStep(
            "think",
            detail=("fixed shared evidence pass: event resolution + funnel + segmented "
                    "metrics + one spec retrieval; no model-visible tools"),
        ))
        return RunResult(
            system=self.name,
            instance_id=iid,
            hypotheses=[output.to_hypothesis()],
            agent_output=[output],
            n_requests=getattr(usage, "requests", 0) or 0,
            n_tool_calls=0,
            total_tokens=input_tokens + output_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_s=round(time.monotonic() - started, 1),
            trace=trace,
        )
