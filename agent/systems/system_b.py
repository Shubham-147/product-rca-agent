"""System B — a single ReAct agent (Pydantic AI) over the deterministic tool layer.

The agent reasons, calls typed tools, reads observations, and emits ranked
`AgentHypothesis` objects (validated: a bad cohort predicate is caught and repaired,
not silently wrong). The tools + harness carry the quality; the agent orchestrates.

Model-agnostic by construction: `run()` uses the configured LiteLLM-proxy model when
`RCA_LLM_BASE_URL` is set, else a passed-in stub (TestModel/FunctionModel). So the whole
loop — tool calls, typed output, budget enforcement — runs and is testable with no API
key; going live is a config swap (see agent/config.py).
"""

from __future__ import annotations

from pathlib import Path

from pydantic_ai import Agent, RunContext
from pydantic_ai.usage import UsageLimits

from .. import tools as T
from ..config import build_model, get_settings
from ..contracts import AgentHypothesis, Cohort
from ..tools import Deps
from .base import RunResult, load_task

INSTRUCTIONS = """\
You investigate a funnel regression with tools. The task already gives the funnel, the
mechanism vocabulary, and the output format — your job is METHOD: use the tools to find
the true cause and the EXACT affected cohort, backing every claim with numbers.

STEP 1 — LOCATE. Call `funnel`. Find WHICH step's conversion dropped post vs pre. The
dropping step points to the mechanism; let the data tell you, do not assume.

STEP 2 — CONFIRM the mechanism with its metric (a defect only counts if it breaches the
PRD SLO — verify the SLO with `retrieve_spec`):
    app_open -> home_view drop        =>  cold_start          (cold_start_p95 over SLO)
    browse/detail step drop, no latency =>  dead_screen        (that step's conversion
                                                                collapses for a cohort)
    checkout_start -> payment_submit  =>  checkout_latency    (checkout_p95 over SLO)
    payment_submit -> order_confirmed =>  payment_failure     (payment_error_rate up)
    crash rate elevated in a cohort   =>  crash_concentration (crash_rate up)
  HOW TO CONFIRM cold_start / dead_screen: their signal is the STEP CONVERSION dropping
  for a COHORT, not a latency breach. A small OVERALL step drop can still hide a large
  cohort drop — so segment `conversion:<from>-><to>` for that step by attributes before
  dismissing it. A flat cold_start_p95 does NOT rule out cold_start. (checkout_latency and
  payment_failure additionally require their metric: checkout_p95 / payment_error_rate.)
  Before you may conclude `innocent_dropoff`, you MUST have checked the relevant metrics
  and found NO SLO breach and NO concentration. NEVER default to innocent when unsure —
  that is a wrong answer on a real fault. Only call innocent if the drop is at an OPTIONAL
  step (upsell) or is fully explained by a traffic-mix shift / pre-existing correlation.

STEP 3 — FIND THE COHORT (most misses happen here — read carefully):
  a. Segment the confirming metric by EACH attribute separately: os, then device_type,
     then geo, then channel, then is_returning. One attribute per call.
  b. Pick the ONE attribute whose split shows the regression CONCENTRATED — one (or a few)
     values with a large delta while the OTHER values are ~flat.
  c. WEIGH DELTA BY SAMPLE SIZE. A large delta in a small segment (n_post < ~200) is NOISE,
     not the fault. Prefer the value where the regression is BOTH large AND well-supported
     (n_post in the hundreds/thousands). Do not chase the biggest number blindly.
  d. The cohort is USUALLY A SINGLE condition (one attribute = one value). Use `in` only
     for several values of the SAME attribute that ALL clearly regressed. DO NOT stack
     conditions across different attributes (os AND geo AND device_type ...) — over-
     conjunction destroys recall and tanks the score. Every extra condition must be
     independently justified by the data.
  e. `cohort_resolve` your predicate. If n_users is 0, a value is wrong — fix it.

STEP 4 — RULE OUT one confounder (old devices? traffic-mix? pre-existing correlation?)
with one more `metric_by_segment`, and state what you ruled out.

STEP 5 — CONVERGE. ~6-10 tool calls is plenty. Once you have the dropping step, a
confirmed SLO breach, the concentrated cohort, and one confounder ruled out, STOP and emit.
Do not keep exploring once you can support an answer.

Back EVERY claim with a tool result (query + numbers in `evidence`). Return the single
best-supported hypothesis first; do not pad with duplicates or contradictory ones.
"""


def build_agent(model=None) -> Agent[Deps, list[AgentHypothesis]]:
    """Construct the System B agent. `model=None` lets `run()` resolve it later."""
    agent = Agent(
        model,
        deps_type=Deps,
        output_type=list[AgentHypothesis],
        instructions=INSTRUCTIONS,
        retries=2,  # output-repair: refeed a validation error before failing the run
    )

    @agent.instructions
    def cohort_domains(ctx: RunContext[Deps]) -> str:
        """Inject the instance's real attribute values so the agent builds cohorts from
        actual data, not guesses (the run-1 failure: os='iOS' matched 0 users)."""
        d = ctx.deps.analytics.attribute_domains()
        lines = [f"  {k}: {v}" for k, v in d.items()]
        return ("VALID COHORT ATTRIBUTE VALUES for this instance — use these EXACT "
                "values; a cohort matching 0 users is wrong:\n" + "\n".join(lines))

    @agent.tool
    def funnel(ctx: RunContext[Deps], segment_by: list[str] | None = None):
        """Session-level conversion for each funnel step, baseline vs recent, with
        deltas. Optionally slice by user attributes (os, device_type, ...)."""
        return T.funnel(ctx.deps, segment_by)

    @agent.tool
    def metric_by_segment(
        ctx: RunContext[Deps], metric: str,
        segment_by: list[str] | None = None, where: Cohort | None = None,
    ):
        """A named metric sliced by segment(s), baseline vs recent, with deltas.
        metric ∈ {conversion:<from>-><to>, checkout_p95, cold_start_p95,
        screen_p95:<screen>, crash_rate, payment_error_rate}. `where` narrows to a cohort."""
        return T.metric_by_segment(ctx.deps, metric, segment_by, where)

    @agent.tool
    def cohort_resolve(ctx: RunContext[Deps], cohort: Cohort):
        """Compile a cohort predicate to the number of users it matches (affected size)."""
        return T.cohort_resolve(ctx.deps, cohort)

    @agent.tool_plain
    def resolve_events(query: str, k: int = 8):
        """Resolve a messy/free-text event term to ranked canonical event concepts."""
        return T.resolve_events(query, k)

    @agent.tool
    def retrieve_spec(ctx: RunContext[Deps], query: str, k: int = 4):
        """Search the PRD (intent, SLOs, design choices) for relevant sections."""
        return T.retrieve_spec(ctx.deps, query, k)

    return agent


class SystemB:
    name = "B"

    def __init__(self, model=None):
        self.settings = get_settings()
        from ..telemetry import setup_telemetry
        setup_telemetry(self.settings)  # no-op unless Langfuse keys are set
        # Resolve the model now: explicit arg > configured proxy model > None (stub set at run)
        self.model = model or build_model(self.settings)
        self.agent = build_agent(self.model)

    def run(self, task_path: str | Path, model=None) -> RunResult:
        import time

        task = load_task(task_path)
        deps = Deps.for_task(str(task_path))
        limits = UsageLimits(
            request_limit=self.settings.request_limit,
            tool_calls_limit=self.settings.tool_calls_limit,
            total_tokens_limit=self.settings.total_tokens_limit,
        )
        run_model = model or self.model
        if run_model is None:
            raise RuntimeError(
                "No LLM model available. Set RCA_LLM_BASE_URL for real runs, or pass a "
                "stub model (TestModel/FunctionModel) to run()."
            )
        model_settings = {
            "temperature": self.settings.temperature,      # determinism (tenet #3)
            "timeout": self.settings.request_timeout_s,    # no infinite network hang
            "max_tokens": self.settings.max_output_tokens,  # bound per-response cost/size
        }
        t0 = time.monotonic()
        try:
            result = self.agent.run_sync(
                task["question"], deps=deps, model=run_model, usage_limits=limits,
                model_settings=model_settings,
            )
        except Exception as e:  # budget exhaustion / model error -> typed, non-fatal
            return RunResult(system=self.name, instance_id=task["instance_id"],
                             hypotheses=[], error=f"{type(e).__name__}: {e}",
                             latency_s=round(time.monotonic() - t0, 1))

        agent_out = list(result.output)
        usage = result.usage  # RunUsage (property in pydantic-ai 2.14)
        in_tok = getattr(usage, "input_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", 0) or 0
        from ..trace import extract_trace
        trace = extract_trace(self.name, task["instance_id"], self.settings.model_name,
                              result.all_messages())
        return RunResult(
            system=self.name,
            instance_id=task["instance_id"],
            hypotheses=[h.to_hypothesis() for h in agent_out],
            agent_output=agent_out,
            n_requests=getattr(usage, "requests", 0) or 0,
            n_tool_calls=getattr(usage, "tool_calls", 0) or 0,
            total_tokens=in_tok + out_tok,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_s=round(time.monotonic() - t0, 1),
            trace=trace,
        )
