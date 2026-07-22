"""System C — a cyclic LangGraph with an investigator and a falsifier.

The investigator uses the same guarded analytical tools and typed output contract as
System B. A separate falsifier then tries to disprove the candidate with counter-
evidence. Rejected candidates cycle back to the investigator with concrete feedback;
accepted candidates end the graph. The cycle is bounded so a hostile or indecisive
model cannot run forever.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.usage import UsageLimits

from .. import tools as T
from ..config import build_model, get_settings
from ..contracts import AgentHypothesis, Cohort
from ..tools import Deps
from ..trace import RunTrace, TraceStep, extract_trace
from .base import RunResult, load_task


INVESTIGATOR_INSTRUCTIONS = """\
You are the investigator in a product-RCA team. Use tools to locate the regressed
funnel step, confirm the matching mechanism, identify the exact concentrated cohort,
and rule out at least one confounder. Segment the confirming metric independently by
os, device_type, geo, channel, and is_returning. Prefer supported deltas over noisy
small segments. Retrieve the relevant PRD SLO. Resolve the final cohort and never emit
a zero-user cohort. Return one best evidence-backed hypothesis.

Pass exactly ONE value in segment_by per call.
Never combine dimensions.
Allowed: ["os"]
Forbidden: ["os", "geo", "channel"]

If falsifier feedback is present, treat it as a failed test that must be addressed:
run the missing comparison or replace the hypothesis. Do not merely argue with it.
Allowed mechanisms: dead_screen, checkout_latency, cold_start, crash_concentration,
payment_failure, innocent_dropoff. Only use innocent_dropoff after ruling out an SLO
breach and cohort concentration.
"""

FALSIFIER_INSTRUCTIONS = """\
You are an adversarial falsifier, not a copy editor. Try to DISPROVE the proposed RCA
using the analytical tools. Check whether the alleged metric actually breached its
PRD SLO, whether the cohort concentration survives comparison with other segments,
whether sample size supports it, whether the cohort resolves to users, and whether a
plausible confounder (device age, traffic mix, or pre-existing correlation) explains
the observation. Set accepted=true only when a serious falsification attempt fails.
Otherwise set accepted=false and give specific, actionable feedback naming the test
or evidence the investigator must address. Never invent numbers.
"""


class FalsificationVerdict(BaseModel):
    accepted: bool
    summary: str
    failed_tests: list[str] = Field(default_factory=list)
    required_follow_up: str = ""


class GraphState(TypedDict):
    question: str
    task_path: str
    candidate: AgentHypothesis | None
    verdict: FalsificationVerdict | None
    feedback: str
    cycle: int
    max_cycles: int
    messages: list[Any]
    requests: int
    tool_calls: int
    input_tokens: int
    output_tokens: int


def _register_tools(agent: Agent, include_domains: bool = True) -> None:
    """Give both agents the identical guarded tool surface used by System B."""
    if include_domains:
        @agent.instructions
        def cohort_domains(ctx: RunContext[Deps]) -> str:
            domains = ctx.deps.analytics.attribute_domains()
            return "VALID ATTRIBUTE VALUES:\n" + "\n".join(
                f"  {key}: {values}" for key, values in domains.items()
            )

    @agent.tool
    def funnel(ctx: RunContext[Deps], segment_by: list[str] | None = None):
        """Baseline vs recent funnel conversion, optionally segmented."""
        return T.funnel(ctx.deps, segment_by)

    @agent.tool
    def metric_by_segment(
        ctx: RunContext[Deps], metric: str,
        segment_by: list[str] | None = None, where: Cohort | None = None,
    ):
        """Baseline vs recent metric, optionally segmented or cohort-filtered."""
        return T.metric_by_segment(ctx.deps, metric, segment_by, where)

    @agent.tool
    def cohort_resolve(ctx: RunContext[Deps], cohort: Cohort):
        """Resolve a typed cohort predicate to its matched user count."""
        return T.cohort_resolve(ctx.deps, cohort)

    @agent.tool_plain
    def resolve_events(query: str, k: int = 8):
        """Resolve free-text event language to canonical concepts."""
        return T.resolve_events(query, k)

    @agent.tool
    def retrieve_spec(ctx: RunContext[Deps], query: str, k: int = 4):
        """Retrieve PRD intent, SLOs, and design constraints."""
        return T.retrieve_spec(ctx.deps, query, k)


def build_investigator(model=None) -> Agent[Deps, AgentHypothesis]:
    agent = Agent(model, deps_type=Deps, output_type=AgentHypothesis,
                  instructions=INVESTIGATOR_INSTRUCTIONS, retries=2)
    _register_tools(agent)
    return agent


def build_falsifier(model=None) -> Agent[Deps, FalsificationVerdict]:
    agent = Agent(model, deps_type=Deps, output_type=FalsificationVerdict,
                  instructions=FALSIFIER_INSTRUCTIONS, retries=2)
    _register_tools(agent)
    return agent


def _usage_update(state: GraphState, result) -> dict[str, Any]:
    usage = result.usage
    return {
        "messages": [*state["messages"], *result.all_messages()],
        "requests": state["requests"] + (getattr(usage, "requests", 0) or 0),
        "tool_calls": state["tool_calls"] + (getattr(usage, "tool_calls", 0) or 0),
        "input_tokens": state["input_tokens"] + (getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": state["output_tokens"] + (getattr(usage, "output_tokens", 0) or 0),
    }


def build_graph(investigator: Agent, falsifier: Agent, deps: Deps, settings, model=None):
    """Compile the bounded investigate -> falsify -> revise cycle."""
    limits = UsageLimits(
        request_limit=settings.request_limit,
        tool_calls_limit=settings.tool_calls_limit,
        total_tokens_limit=settings.total_tokens_limit,
    )
    model_settings = {
        "temperature": settings.temperature,
        "timeout": settings.request_timeout_s,
        "max_tokens": settings.max_output_tokens,
    }

    def investigate(state: GraphState) -> dict[str, Any]:
        prompt = state["question"]
        if state["feedback"]:
            prompt += ("\n\nFALSIFIER FEEDBACK FROM THE PREVIOUS CYCLE:\n" +
                       state["feedback"])
        result = investigator.run_sync(prompt, deps=deps, model=model,
                                       usage_limits=limits, model_settings=model_settings)
        return {"candidate": result.output, "cycle": state["cycle"] + 1,
                **_usage_update(state, result)}

    def falsify(state: GraphState) -> dict[str, Any]:
        assert state["candidate"] is not None
        prompt = (
            "Original investigation question:\n" + state["question"] +
            "\n\nCandidate to falsify:\n" +
            json.dumps(state["candidate"].model_dump(), default=str, indent=2)
        )
        result = falsifier.run_sync(prompt, deps=deps, model=model,
                                    usage_limits=limits, model_settings=model_settings)
        verdict = result.output
        feedback = verdict.summary
        if verdict.failed_tests:
            feedback += "\nFailed tests: " + "; ".join(verdict.failed_tests)
        if verdict.required_follow_up:
            feedback += "\nRequired follow-up: " + verdict.required_follow_up
        return {"verdict": verdict, "feedback": feedback,
                **_usage_update(state, result)}

    def route(state: GraphState) -> Literal["revise", "finish"]:
        assert state["verdict"] is not None
        if state["verdict"].accepted or state["cycle"] >= state["max_cycles"]:
            return "finish"
        return "revise"

    graph = StateGraph(GraphState)
    graph.add_node("investigator", investigate)
    graph.add_node("falsifier", falsify)
    graph.add_edge(START, "investigator")
    graph.add_edge("investigator", "falsifier")
    graph.add_conditional_edges("falsifier", route,
                                {"revise": "investigator", "finish": END})
    return graph.compile()


class SystemC:
    name = "C"

    def __init__(self, model=None, max_cycles: int = 2):
        if max_cycles < 1:
            raise ValueError("max_cycles must be at least 1")
        self.settings = get_settings()
        from ..telemetry import setup_telemetry
        setup_telemetry(self.settings)
        self.model = model or build_model(self.settings)
        self.max_cycles = max_cycles

    def run(self, task_path: str | Path, model=None) -> RunResult:
        task = load_task(task_path)
        run_model = model or self.model
        if run_model is None:
            raise RuntimeError(
                "No LLM model available. Set RCA_LLM_BASE_URL for real runs, or pass "
                "a stub model to SystemC/run()."
            )
        started = time.monotonic()
        deps = Deps.for_task(str(task_path))
        investigator = build_investigator(run_model)
        falsifier = build_falsifier(run_model)
        graph = build_graph(investigator, falsifier, deps, self.settings, run_model)
        initial: GraphState = {
            "question": task["question"], "task_path": str(task_path),
            "candidate": None, "verdict": None, "feedback": "", "cycle": 0,
            "max_cycles": self.max_cycles, "messages": [], "requests": 0,
            "tool_calls": 0, "input_tokens": 0, "output_tokens": 0,
        }
        try:
            final = graph.invoke(initial, config={"recursion_limit": 2 * self.max_cycles + 2})
        except Exception as exc:
            return RunResult(system=self.name, instance_id=task["instance_id"],
                             hypotheses=[], error=f"{type(exc).__name__}: {exc}",
                             latency_s=round(time.monotonic() - started, 1))

        candidate = final["candidate"]
        trace = extract_trace(self.name, task["instance_id"], self.settings.model_name,
                              final["messages"])
        verdict = final["verdict"]
        trace.steps.append(TraceStep(
            "think", detail=(f"falsifier {'accepted' if verdict.accepted else 'rejected'} "
                             f"candidate after {final['cycle']} cycle(s): {verdict.summary}"),
        ))
        return RunResult(
            system=self.name, instance_id=task["instance_id"],
            hypotheses=[candidate.to_hypothesis()], agent_output=[candidate],
            n_requests=final["requests"], n_tool_calls=final["tool_calls"],
            total_tokens=final["input_tokens"] + final["output_tokens"],
            input_tokens=final["input_tokens"], output_tokens=final["output_tokens"],
            latency_s=round(time.monotonic() - started, 1), trace=trace,
        )
