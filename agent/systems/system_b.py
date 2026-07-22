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
You are a product-analytics agent doing root-cause attribution on a mobile e-commerce
funnel. A change may have been introduced at the changepoint; compare the BASELINE
(pre) vs RECENT (post) periods and explain any conversion regression.

METHOD (evidence over assertion):
1. Call `funnel` first to locate WHICH step's conversion drops post vs pre (the symptom).
   The step that drops points to the mechanism — do NOT assume; let the funnel tell you.
2. Match the worst step to its mechanism and CONFIRM with the corresponding metric:
     app_open -> home_view drop .......... cold_start        (confirm: cold_start_p95)
     a browse/detail step drop ........... dead_screen       (confirm: that step's
                                           conversion collapses for a cohort, no latency)
     checkout_start -> payment_submit .... checkout_latency  (confirm: checkout_p95)
     payment_submit -> order_confirmed ... payment_failure   (confirm: payment_error_rate)
     crashes elevated in a cohort ........ crash_concentration(confirm: crash_rate)
   A metric only confirms a defect if it breaches the PRD SLO (check with `retrieve_spec`).
3. Identify WHO is affected: segment the confirming metric by user attributes to find the
   cohort where it regressed, then size it with `cohort_resolve`.
4. RULE OUT confounders before committing: is it just old devices? a traffic-mix shift?
   a pre-existing correlation? Check with another `metric_by_segment` call (e.g. hold the
   suspect attribute fixed and slice by another). State what you ruled out.
5. Use `resolve_events` when unsure what a messy event name means, and `retrieve_spec`
   to check the product's intent/SLOs. If the drop is at an OPTIONAL step (upsell) or has
   no metric breach and is explained by traffic-mix/design, it is `innocent_dropoff`.

CHOOSING THE COHORT (this is scored — get it right):
- The affected cohort is the NARROWEST predicate that captures where the metric
  regressed. Add a condition ONLY if the metric clearly regressed for that attribute
  value and NOT for the others. Example shape (NOT the answer for any case): if a metric
  regressed sharply for one os value but barely moved for the rest, the cohort is that
  one os value alone — do not include the others.
- Do NOT add extra attributes (device_type, is_returning, geo, ...) unless the data
  shows the regression is specific to them; every unjustified condition lowers your
  score. Prefer the fewest conditions.
- Sanity-check before finalizing: the metric delta must be LARGE inside the cohort and
  SMALL outside it. If not, your cohort is wrong.

EFFICIENCY (you have a limited tool budget — converge, don't wander):
- Investigate deliberately with a few TARGETED queries, not dozens. A normal case needs
  ~4-8 tool calls total: funnel, one or two confirming metrics, a cohort segmentation, a
  confounder check, cohort_resolve.
- As soon as you have (a) where the funnel drops, (b) a confirming metric breach, (c) the
  cohort, and (d) one confounder ruled out — STOP and emit your hypothesis. Do not keep
  exploring once you can support an answer.

RULES:
- Back EVERY claim with a tool result (put the query + numbers in `evidence`).
- `affected_cohort` is a structured predicate over {os, device_type, device_age_months,
  geo, channel, is_returning} — as narrow as the data supports.
- Return only well-supported hypotheses; do not pad with duplicates or contradictory ones.
- mechanism_type ∈ {dead_screen, checkout_latency, cold_start, crash_concentration,
  payment_failure, innocent_dropoff}.
- If there is NO actionable product fault (by design / traffic-mix / pre-existing
  correlation), return ONE hypothesis with mechanism_type "innocent_dropoff" explaining why.
- Return hypotheses ranked most-likely first.
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
