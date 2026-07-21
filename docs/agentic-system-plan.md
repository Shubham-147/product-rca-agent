# Agentic System Plan — RCA Agent (System B first)

**Branch:** `agent/system-b` (forked from `main`) · **Owner:** Vinay · **Status:** proposal for staff review
**Related:** [generated-data-overview.md](generated-data-overview.md) · [ui-plan.md](ui-plan.md) · [project-brief.md](project-brief.md)

> This plan is written to be **red-teamed**. Every non-obvious choice is stated as a
> decision with a rationale and an alternative (§10). It is built from the design
> brief + our simulator/eval contract — deliberately *not* from any existing agent
> branch.

---

## 1. Objective & scope

Build **System B** — a single ReAct agent that takes one instance (warehouse +
task) and returns ranked, evidence-backed `Hypothesis` objects — and make it
**genuinely good**: correct on the benchmark, cheap enough to run at scale, and
fully observable. System **A** (vanilla RAG) is built first, but only as the
**baseline foil** that proves the loop and quantifies "retrieval ≠ attribution".
System **C** (multi-agent + Falsifier) is **explicitly deferred** until B's
evaluation shows a ceiling that a cyclic critic would break.

**The bet:** quality comes from the **tools + the harness + the eval loop**, not
from agent cleverness. A mediocre agent with excellent tools and a tight eval loop
beats a clever agent flying blind. So we invest there first.

**Non-goals for v1:** System C, multi-agent orchestration, cross-encoder reranking
(until measured), the LLM-judge (until objective metrics are solid), the UI wiring
(the trace protocol is defined here so it's free later).

---

## 2. Design tenets (the bar for every PR)

1. **Simplicity first; complexity must be *earned by eval*.** No component ships
   because it's in the design doc — it ships because a metric moved. Measure, then add.
2. **Typed contracts at every boundary.** `Hypothesis`, tool inputs/outputs, and
   `TraceEvent` are Pydantic models. A malformed cohort predicate is a caught error,
   not a silent wrong query.
3. **Deterministic & reproducible.** `temperature=0`, pinned model IDs, fixed seeds;
   every run records model+version+params. Same inputs → same trace.
4. **Observable by default.** No code path without a span. The trace *is* the
   debugger and the eval substrate. If it isn't traced, it didn't happen.
5. **Eval-in-the-loop.** The harness is the fitness function. Nothing merges without
   a dev-set number attached. Regressions are build failures.
6. **Cost-bounded.** Per-run and total token/USD budgets are enforced, not hoped for.
   Cost-per-case is a first-class, reported metric.
7. **Fail typed.** Tools return typed errors the agent can recover from; refusals and
   guardrail trips are logged, never swallowed.

---

## 3. Architecture (layers, bottom-up)

```
                    ┌─────────────────────────────────────────────┐
   FastAPI /analyze │  System A (RAG)      System B (ReAct agent)  │  ← systems
        (SSE)  ─────┤        \                    /                │
                    │         └── Tool layer ────┘                 │  ← the value
                    │   funnel · metric_by_segment · cohort_resolve│
                    │   retrieve_spec · resolve_events  (run_sql*) │
                    ├─────────────────────────────────────────────┤
                    │  LLM client (provider-abstracted, tiered)    │  ← model layer
                    │  Warehouse session (DuckDB, read-only)       │
                    │  Guardrails (SQL / cohort / output / budget) │
                    ├─────────────────────────────────────────────┤
                    │  Telemetry: OTel spans → Phoenix  +  SSE     │  ← cross-cutting
                    │  Contracts: Hypothesis, TraceEvent           │
                    └─────────────────────────────────────────────┘
                    eval/ harness  ──►  scorer (already built)  ──►  metrics
```

**Reuse, don't rebuild:** `simulator.schemas.Hypothesis`, the `run(warehouse, task)
-> list[Hypothesis]` contract, `eval/scorer.py`, and the generated benchmark all
exist on `main`. The agent plugs into them.

### Proposed layout (fresh under `agent/`)
```
agent/
  config.py            pydantic-settings: models, budgets, paths, telemetry
  contracts.py         re-export Hypothesis; define TraceEvent (the UI/OTel event)
  llm/client.py        LiteLLM gateway (OpenAI default); tiered (strong/cheap); budget-aware
  warehouse.py         per-instance read-only DuckDB session
  analytics.py         deterministic SQL compiler + executor (OWNS all SQL)
  tools/
    funnel.py          conversion by step, pre/post (± segment_by)
    metric_by_segment.py  a metric sliced by segment(s), pre/post — mechanism + confounder analysis
    cohort_resolve.py  compile a whitelisted WHERE → user-id set + size
    retrieve_spec.py   dense RAG over the PRD (Chroma)
    resolve_events.py  hybrid BM25 + dense (rerank later) over the taxonomy
    run_sql.py         OPTIONAL guarded SELECT escape hatch (off by default)
    guardrails.py      SQL/cohort/output validation
  systems/
    base.py            System protocol
    system_a.py        vanilla RAG baseline
    system_b.py        Pydantic AI ReAct agent
  telemetry/otel.py    OTel + Phoenix exporter; emit() → span + SSE
  api/app.py           FastAPI /analyze (SSE), /score
  cli.py               run one/all, build-index
eval/                  extend: run_suite.py (batch) + metrics aggregation
```

---

## 4. The tools (where quality lives — spec them tightly)

**Who writes the SQL? The compiler does, not the agent.** Deliberate split: the
**agent forms analytical *intent*** (a metric, a segmentation, a cohort predicate —
a small typed DSL), and a **deterministic analytics compiler owns SQL generation +
execution**. The agent never emits raw SQL on the default path. Why: tool-call
accuracy is a scored metric and hand-written SQL against a *cursed* schema is where
agents fail (wrong column names, timeouts, injection surface); the agent's value is
*reasoning* (which cohort, which mechanism, which confounder), not SQL authorship.
RCA is a **bounded** set of analytical ops, so a few parameterised tools cover ~all
of it. A raw `run_sql` escape hatch exists but is **off by default** — enabled only
if the eval shows the structured tools are too narrow (measure-first).

Each tool: **typed in/out, guarded, traced, recoverable.** All read-only.

| Tool (agent-facing *intent*) | Signature (sketch) | The compiler does | Emits to trace |
| :-- | :-- | :-- | :-- |
| `funnel` | `(segment_by?, period='both') -> [{step, conv_pre, conv_post}]` | builds funnel-conversion SQL, optionally sliced | the symptom table |
| `metric_by_segment` | `(metric, segment_by:[str], where?, period) -> rows` | compiles a segmented aggregate; `metric ∈ {conversion, checkout_p95, crash_rate, payment_error_rate, cold_start_rate}` | metric, segments, deltas |
| `cohort_resolve` | `(where:str) -> {n_users, user_ids}` | validate `where` (whitelist cols) → `SELECT DISTINCT user_id … WHERE` | predicate, n_users |
| `retrieve_spec` | `(query, k=4) -> [chunk]` | dense RAG over the PRD | query, chunk ids, scores |
| `resolve_events` | `(query, k=8) -> [{name, score, source}]` | hybrid BM25 + dense over the taxonomy | candidates + chosen |
| `run_sql`* | `(sql) -> {cols, rows}` | *escape hatch, OFF by default* — SELECT-only, allow-list, timeout, row cap | sql, rows |

`metric_by_segment` is the workhorse: mechanism confirmation ("`checkout_p95` by
`os`, recent") and confounder analysis ("`crash_rate` + retention by `device_age`,
holding `os`") are both just segmented aggregates — no raw SQL needed.

**Tool design principles that move the metrics:**
- `resolve_events` is the RAG-scored tool. **v1 = BM25 + dense fusion (RRF), no
  cross-encoder.** Add reranking only if event-resolution P/R (vs the hidden canonical
  map, dev-mode) is under target. Measure-first (§10 D2).
- The **analytics compiler is the highest-leverage component**: it turns the agent's
  cohort/metric *intent* into concrete pre/post numbers — what separates B from A.
  Make its outputs rich (the deltas the agent needs to justify a mechanism).
- Every tool validates inputs and returns a **typed error** (`{error, hint}`) the
  agent reads and retries — never an exception that kills the run. Tool-call accuracy
  is scored; the tool owns making success easy.

### 4.1 Cohort predicate — a structured DSL (not free-form SQL)

Per D3/D8, `affected_cohort` is a **validated predicate AST**, not a SQL string. The
agent emits structure; the compiler turns it into SQL. Strictly safe (no SQL parsing),
deterministic, directly UI-renderable, and normalizable for exact cohort-F1 scoring.

```python
Col = Literal['os','device_type','device_age_months','geo','channel','is_returning']
Op  = Literal['eq','ne','lt','le','gt','ge','in']

class Condition(BaseModel):
    col: Col
    op: Op
    value: str | int | bool | list[str | int]

class Cohort(BaseModel):        # cohorts here are simple: an AND of conditions,
    all: list[Condition]        # with an optional OR group
    any: list[Condition] = []
```

Example — the Old-Device cohort:
`Cohort(all=[{col:'os',op:'eq',value:'Android 12'}, {col:'device_age_months',op:'gt',value:24}])`
→ compiler → `os = 'Android 12' AND device_age_months > 24`.

**Contract impact (tracked):** changes `Hypothesis.affected_cohort` from `str` to
`Cohort` in `simulator/schemas.py`, and the scorer's `compile_cohort` compiles the AST
instead of executing a `WHERE` string — a net safety win. Pydantic AI emits this
structure natively.

---

## 5. System B — the agent

- **Framework:** **Pydantic AI** — native tool-calling + a *validated* `Hypothesis`
  output. Type-safe output is a correctness requirement (a malformed cohort predicate
  = a silently wrong query). (Alternative: a raw provider tool-loop — simpler, less
  magic; staff call in §10 D4.)
- **Loop:** ReAct — the agent reasons, calls tools, reads observations, refines,
  emits ranked hypotheses. **Bounded:** max tool-calls per run, max wall-clock, hard
  token/USD budget. On budget exhaustion it must emit its best-so-far, not crash.
- **Prompting:** a compact system prompt encoding the task, the funnel, the mechanism
  taxonomy, the cohort language, and the *rules of evidence* ("name a mechanism, not a
  symptom; back every claim with a query; state confounders you ruled out"). The task
  prompt (`data/tasks/task_<id>.json`) is passed verbatim.
- **Output repair:** if the model returns an invalid `Hypothesis` (bad cohort
  predicate, unknown mechanism_type), the validation error is fed back once for repair
  before the run is scored.
- **Determinism:** `temperature=0`, pinned model, no hidden randomness.

**System A (baseline), for contrast:** chunk+embed PRD/dict/event-sample → retrieve
on the task → single generate. No SQL, no aggregation. Built to fail, and to *quantify*
the failure (the ≥30pp story starts here).

---

## 6. The harness & evaluation (the fitness function)

Reuse `eval/scorer.py` and `eval/run_case.py`; extend with:
- **`eval/run_suite.py`** — run a system across the dev set (8) and the blinded set,
  parallelised, budget-aware, writing per-case results + a run manifest.
- **Metrics aggregation** — the full suite from the brief, computed from the scorer:
  attribution top-1 / recall@3, cohort-ID F1, decoy FP-rate, confounder resistance,
  event-resolution P/R, tool-call accuracy, cost/latency per case, detection-vs-severity.
- **A dev loop:** every change is run on the dev set; results diffed against the last
  run; a regression on any tracked metric fails the check. The harness is CI-able.
- **Judge (deferred):** LLM-as-judge on evidence faithfulness, cross-family model,
  calibrated on ~15–30 human labels — added only once the objective metrics are stable.

The eval is the source of truth for "is B good yet?" — not vibes, not a demo.

---

## 7. Observability — OpenTelemetry + Phoenix (from day one)

**Why it's Phase 0, not an afterthought:** cost, latency, and tool-call accuracy are
*comparative* metrics across A and B; you cannot compare what you didn't instrument
uniformly. And the trace is how we debug a 12-step agent run.

- **Spine:** OpenTelemetry spans exported to **Arize Phoenix Cloud** (shared — so
  Vinay, Shubham, and mentors all see the same traces). Because the spine is OTel,
  the exporter endpoint is a one-line swap to a local Phoenix if ever needed — no
  lock-in. OpenInference auto-instruments the LLM client; tools/systems get manual spans.
- **Span tree per run:**
  `run{system,instance}` → `llm.call{model,tokens,cost}` · `tool.run_sql{sql,rows}` ·
  `tool.resolve_events` → `retrieval{candidates[bm25/dense/score]}` · `tool.cohort_stats`
  · `hypothesis{...}` · `score{top1,f1,decoy_fp}`.
- **Attributes to standardize** (so Phoenix can slice them): `system`, `instance_id`,
  `fault_type`, `severity`, `model`, `tokens_in/out`, `cost_usd`, `latency_ms`,
  `tool.name`, `tool.ok`, `resolved.canonical`, `score.*`, `budget.spent`.
- **One emitter, two sinks:** a single `emit(TraceEvent)` writes both an OTel span
  **and** the SSE event for the UI (the [ui-plan.md](ui-plan.md) §5 protocol). Instrument
  once; get the observability dashboard *and* the Investigation Workbench feed for free.
- **Scores as trace metadata:** logging each run's score into the trace turns Phoenix
  into the live comparison matrix + per-case grid — from *real* numbers, sliceable by
  system/fault/severity.
- **Cost governance:** budgets enforced in the LLM client; spend logged per run;
  a run that would exceed the cap stops and emits best-so-far.

---

## 8. How it plugs into what exists

- **Contract:** each system is `run(warehouse, task) -> list[Hypothesis]`; drop into
  `eval/run_case --system agent.systems.system_b`. No harness changes needed.
- **Data:** the generated benchmark on `main` (`data/`, git-ignored, regenerable).
- **UI:** the SSE trace protocol is emitted by the telemetry layer, so the React
  Workbench (later) wires straight in.
- **Coexistence:** `agent/` is new and additive; `simulator/` and `eval/` are untouched
  except an additive `eval/run_suite.py`.

---

## 9. Phased execution (each phase gates on *observable proof*, not code volume)

| Phase | Deliverable | Done = (the gate) |
| :-- | :-- | :-- |
| **0 · Spine** (~0.5d) | `agent/` skeleton, config, LLM client, **OTel→Phoenix**, `TraceEvent` | a trivial LLM call shows a full trace in Phoenix; contracts import from `simulator` |
| **1 · Foundation (+A)** (~1.5d) | the **shared foundation** — 5 tools (dense+BM25, no rerank) + analytics compiler + guardrails — plus System A as its first consumer, wired to `eval/run_case`. (A may be owned by Shubham; it imports this foundation.) | A runs on `inst_001` end-to-end → a (bad) `Hypothesis` → scored by the harness → fully traced. *The whole loop proven on the baseline.* |
| **2 · System B** (~2d) | Pydantic AI ReAct agent, bounded, typed output + repair | B **beats A** on the dev set; every tool/LLM call + cost/latency traced per case |
| **3 · Make B good** (~2d) | eval-driven iteration: prompts, tool ergonomics, add rerank *iff* P/R demands it, tune cohorts | B clears the target bars on the dev set; harness catches regressions; (optional) judge added |
| **4 · Scale / maybe C** (later) | full blinded run; comparison matrix + per-case grid from real numbers; C only if B's confounder-resistance is the proven ceiling | real A-vs-B (and C) numbers in Phoenix + the UI |

**Phase 1 is the linchpin:** proving tools → system → contract → scorer → telemetry
end-to-end on the *baseline* de-risks everything. If the loop is solid, B is just
"a better brain on the same nervous system."

---

## 10. Decisions for staff validation (I have a default; challenge them)

| # | Decision | My default | Alternative / risk |
| :-- | :-- | :-- | :-- |
| D1 | LLM provider / gateway | **OpenAI via a self-hosted LiteLLM proxy** (native cross-provider + central budget/spend/fallback); Pydantic AI points at its `base_url` | OpenRouter — hosted 3rd-party in the data path (markup + routing variance → bad for reproducible eval). Risk: LiteLLM is *redundant with Pydantic AI's own multi-provider* — so use it for governance (budget/spend), not just switching; pin model + disable fallback on scored runs; instrument spans at ONE layer only |
| D2 | Cross-encoder rerank in `resolve_events` | **Defer** — ship BM25+dense (RRF); add rerank only if event-res P/R < target | Ship rerank now (design doc says so) — but that's un-measured complexity. *Confirmed: add-on later.* |
| D3 | Cohort predicate language | **Structured DSL** (predicate AST, §4.1) — validated, safe, UI-renderable, exactly scorable | free-form SQL `WHERE` — expressive but a parsing/injection surface. *Chosen: DSL.* |
| D4 | Agent framework for B | **Pydantic AI** (typed output) — *confirmed* | raw provider tool-loop — simpler, fewer deps |
| D5 | Scope / dependency | **Foundation-first**, then A and B are *parallel consumers* of it; C deferred | No B→A code dependency. If A is built separately it MUST import the same foundation (tools/contracts/telemetry) or the comparison isn't apples-to-apples |
| D6 | Judge & UI | both deferred; trace protocol defined now so they're cheap later | build now — premature |
| D7 | Telemetry | **OTel + Phoenix Cloud** (shared — chosen) | local Phoenix — trivial exporter swap; no advantage here (synthetic data, want shared visibility) |
| D8 | Who writes SQL | **analytics compiler owns SQL; agent forms intent** (a small DSL) | agent writes raw SQL — flexible but tanks tool-call accuracy + adds guardrail surface |

**Open questions I need your call on:** target model(s) + monthly budget ceiling;
and whether the LLM-judge is in-scope for the 22 Jul gate.
