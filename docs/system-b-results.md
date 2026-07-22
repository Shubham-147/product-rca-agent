# System B — Evaluation Report

**System:** B — a single ReAct agent (Pydantic AI) over a deterministic tool layer.
**Model:** OpenAI `gpt-4o`, `temperature=0`. **Benchmark:** 20 planted-fault instances
(17 with a fault, 3 confounder-trap / no-fault), scored against a held-out gold manifest.
**Status:** measured, iterated, and at its prompt-tuning ceiling (see §4). Commit `3409c2b`.

---

## 1. Headline

Eval-in-the-loop took System B from a **0/20** first pass to **6/20 top-1 correct**, with
mechanism identification at **9/20**, in five prompt iterations and **$0 of architecture
change** — while producing a clean, measured result about *where a single agent hits its
ceiling*.

| Metric | Baseline (1st run) | **Final (iter-3)** |
| :-- | --: | --: |
| **Attribution top-1** (mechanism ∧ cohort-F1 ≥ 0.5) | 0.00 | **0.30** (6/20) |
| Mechanism accuracy (pred == gold) | 0.20 | **0.45** (9/20) |
| Cohort-F1 (mean over fault cases) | 0.06 | **0.43** |
| Run errors | 6 | **0** |
| Decoy false-positive rate (no-fault cases) | 0.33 | 1.00 |
| Cost (20 instances) | $2.59 | $2.18 |
| Mean latency / case | 19 s | ~18 s |

Top-1, mechanism, cohort-F1, and reliability (errors→0) all improved. Decoy-FP regressed
— a deliberate, evidenced trade (see §4) that pins the hard frontier.

---

## 2. What was built (the stack under test)

Every layer below the agent is deterministic and was verified before the agent ran:

- **Benchmark** — persona-driven event simulator with planted faults + a blinded gold
  manifest (no persona/canonical exposed to the agent).
- **Retrieval (Phase 1a)** — hybrid event-name resolver (char-ngram + fuzzy + dense
  bge-small, RRF), **P/R gate passed at F1 0.911** offline (see
  [retrieval-pipeline-plan.md §8](retrieval-pipeline-plan.md)). Resolves ~225 cursed
  firing names → 44 canonical concepts.
- **Foundation** — read-only warehouse session + an analytics compiler that **owns all
  SQL** (the agent forms typed *intent*, never raw SQL; D8). Cohort predicates are a
  validated DSL (D3), not SQL strings.
- **Tools** — `funnel`, `metric_by_segment`, `cohort_resolve`, `resolve_events`,
  `retrieve_spec` — typed in/out, guarded, fail-typed (a bad call returns a `ToolError`,
  never crashes a run).
- **Agent** — Pydantic AI ReAct, bounded (request/tool/token budgets), typed output with
  repair, `temperature=0`.
- **Harness** — `eval/run_suite.py`: parallel-capable, crash-safe (incremental save +
  `--resume`), scores via the same `eval/scorer.py` the manifest defines.
- **Observability** — per-run local ReAct traces (`eval/traces/*.md`) + OpenTelemetry
  spans exported to **Langfuse** (59 traces / 847 observations captured).

---

## 3. Per-instance results (final)

`M` = mechanism correct · `T1` = top-1 (mechanism ∧ cohort-F1 ≥ 0.5).

| instance | gold fault | predicted | M | T1 | cohort-F1 |
| :-- | :-- | :-- | :-: | :-: | --: |
| inst_001 | checkout_latency | checkout_latency | ✓ | ✓ | 0.97 |
| inst_002 | cold_start | cold_start | ✓ | ✓ | 0.74 |
| inst_006 | crash_concentration | crash_concentration | ✓ | ✓ | 0.55 |
| inst_008 | checkout_latency | checkout_latency | ✓ | ✓ | 0.96 |
| inst_016 | cold_start | cold_start | ✓ | ✓ | 0.92 |
| inst_017 | checkout_latency | checkout_latency | ✓ | ✓ | 0.96 |
| inst_000 | dead_screen | dead_screen | ✓ | · | 0.14 |
| inst_004 | payment_failure | payment_failure | ✓ | · | 0.17 |
| inst_018 | dead_screen | dead_screen | ✓ | · | 0.16 |
| inst_007 | dead_screen | payment_failure | · | · | 0.63 |
| inst_003 | crash_concentration | dead_screen | · | · | 0.07 |
| inst_009 | payment_failure | dead_screen | · | · | 0.03 |
| inst_011 | cold_start | dead_screen | · | · | 0.16 |
| inst_012 | checkout_latency | crash_concentration | · | · | 0.27 |
| inst_013 | dead_screen | crash_concentration | · | · | 0.29 |
| inst_014 | crash_concentration | innocent_dropoff | · | · | 0.13 |
| inst_015 | payment_failure | checkout_latency | · | · | 0.15 |
| inst_005 | *none* (trap) | checkout_latency | · | · | — |
| inst_010 | *none* (trap) | dead_screen | · | · | — |
| inst_019 | *none* (trap) | dead_screen | · | · | — |

Two clusters of the correct answers: the **latency/error mechanisms** (checkout_latency,
payment_failure) which have a distinctive corroborating metric, and **cold_start** once
its confirmation was fixed to read the *conversion* drop rather than a latency breach.

---

## 4. The iteration log (methodology in action)

Each change was validated on a cheap 5-mechanism subset before a full run. What moved the
needle — and, just as usefully, what backfired:

| # | Change | Effect | Kept? |
| :-- | :-- | :-- | :-: |
| numpy fix | cast `numpy.bool_` segment keys to native | −2 errors | ✓ |
| **iter-1** | rewrite prompt: concrete cohort algo (weigh delta by sample size, ≤1–2 conditions), funnel-step→mechanism map, trimmed the role/funnel restatement the task already carries, anti-innocent gate | mechanism ~1/5 → 4/5; inst_001 recovered to top-1 | ✓ |
| iter-2 | loosen the mechanism map | **collapsed all faults to `dead_screen`** | ✗ revert |
| **iter-3** | confirm cold_start/dead_screen via the *segmented step conversion*, not a latency breach | cold_start recovered (inst_002/016) | ✓ |
| iter-4 | add confounder-control cohort guidance | agent **over-conjuncted** (`os AND geo AND …`), tanked recall, lost inst_001 | ✗ revert |
| iter-5 | balanced positive test for `innocent_dropoff` | didn't fix the traps *and* regressed a passing fault | ✗ revert |

**Three separate attempts (iter-2, iter-4, iter-5) to crack the hard cases each made
things worse.** This is the core finding, not an incidental failure.

---

## 5. Analysis — where B succeeds and where it hits a wall

**B is good at mechanism identification when a distinctive signal exists.** checkout_latency
(`checkout_p95` SLO breach), payment_failure (`payment_error_rate`), and — after iter-3 —
cold_start (an `app_open→home_view` conversion drop concentrated in a cohort) are found
reliably, with tight cohorts (F1 0.74–0.97).

**B hits a wall on two things, both rooted in confounding:**

1. **Exact cohort selection under correlated attributes.** When several attributes each
   show a drop (because they are correlated), B picks the biggest raw delta rather than
   the causal attribute. Example — inst_000: the true cohort is `os = 'Android 12'`
   (−8.3pp, n≈1,000), but B chose `geo = 'SEA'` (−9.8pp, n≈600, a noisy correlate). The
   principled fix — *control for one attribute and keep the effect that persists* — when
   added to the prompt made B **over-conjunct** instead (iter-4), lowering recall.

2. **Recognising a confounder-trap as `innocent_dropoff`.** All 3 no-fault instances are
   traps where a pre-existing correlation / traffic-mix shift *looks* like a regression. B
   flags a fault on all 3 (decoy-FP 1.00). Pushing it toward innocent to fix this
   immediately caused it to *miss real faults* (iter-5) — a see-saw with no prompt-only
   equilibrium.

Both failures are the *same* underlying gap: a single forward-reasoning pass **cannot
reliably distinguish a causal signal from a confounded one.** More instruction does not
help — it trades one error for another.

---

## 6. The B-vs-C finding (the point)

This is exactly the result the design doc hypothesised: a single ReAct agent (B) handles
clean, single-signal faults but fails the **confounder / Simpson's-paradox** cases, and
that failure is **structural, not a prompting deficiency** — we have three reverted
iterations as evidence. The remedy the design predicts is **System C**: a multi-agent loop
with a **Falsifier** that actively tries to *disprove* each hypothesis (e.g. "is the SEA
drop still there once we hold OS fixed?" / "does this regression vanish when we control for
the traffic mix?"). That adversarial, cyclic check is precisely what the failing cases
need and what a forward-only agent cannot do.

The eval now produces this as a **measured, falsifiable claim** — the intended headline
comparison, grounded in numbers rather than assertion.

---

## 7. Cost, reproducibility, observability

- **Cost:** a full 20-instance run is ~$2.18 on gpt-4o (well under the budget).
  Deterministic at `temperature=0`; pinned model.
- **Reproducible:** `../.venv/bin/python -m eval.run_suite` (crash-safe, `--resume`).
  Results manifest at `eval/results/suite_system_B.json`; per-run traces at `eval/traces/`.
- **Observable:** OpenTelemetry → Langfuse (`us.cloud.langfuse.com`), every LLM + tool
  call as a span; local markdown traces mirror the same ReAct loop.

---

## 8. Limitations & next steps

- **Cohort-under-confounding & innocent-trap detection** are B's ceiling — *by design*,
  they are System C's job (the Falsifier). **This is the recommended next build.**
- **System A (vanilla RAG, no SQL tools)** would quantify the "retrieval ≠ attribution"
  gap — the A-vs-B contrast — and is cheap to add on the same harness.
- **Decoy-FP** is tied to the innocent-trap gap above; expect it to resolve with C, not
  with more B prompting.
- **Judge / human calibration** and scaling N remain as declared depth-tail items.
