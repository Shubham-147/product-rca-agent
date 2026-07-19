# My Two Deliverables — Persona-Driven Data + Testbench UI

**Owner:** Vinay (teammate Shubham owns the agent — "Product RCA Agent")
**Scope:** (1) the simulated product + persona-based event generation with planted gaps; (2) a UI to run and compare the solutions.
**Gate:** 22 July 2026. **Companion:** [plan.md](plan.md), [project-brief.md](project-brief.md)

> Both deliverables can be built **without reading the teammate's code**, provided we agree ONE contract up front (§0). Everything I own (data, funnel analytics, scorer, and most of the UI) depends only on that contract — not on the agent being finished.

---

## 0. The one thing to sync with Shubham (do first)

Three interfaces. Nothing else about his agent matters to me.

1. **Event schema** — the DuckDB tables the agent's `run_sql` tool reads (§1.4).
2. **`Hypothesis` output schema** — what the agent returns, so the UI + scorer can consume it (§1.5).
3. **How the agent is invoked** — a callable/endpoint the UI hits: `analyze(case_id, system) -> stream of steps + final Hypothesis[]`. If his agent is a Python function, I wrap it in FastAPI. If it's already a service, I call it.

Agree these once → I build against a **mock agent** and never block on him.

---

# Deliverable 1 — Product + persona-driven events with planted gaps

## 1.1 The product (concrete, ~15 screens)
One mobile e-commerce app. **Core funnel:**
`app_open → home_view → browse/search → product_detail → add_to_cart → cart_view → checkout_start → payment → order_confirmed`

**Off-funnel screens** (realism + decoys): `profile · wishlist · order_history · search_empty · settings · upsell_interstitial (DECOY: designed to shed users) · onboarding_tutorial (DECOY: skippable)`.

## 1.2 Personas (the organizing idea — heterogeneity + confounders made tangible)
Each persona = an attribute profile + a behavioural model (intent, session frequency, per-step conversion tendency). Personas are how we get realistic heterogeneity **and** bake confounders into the baseline so they're structural, not decorative.

| Persona | Attributes | Behaviour | Role |
| :-- | :-- | :-- | :-- |
| **Loyal Converter** | returning, new flagship iOS/Android | high intent, high conversion, frequent | healthy baseline |
| **Bargain Hunter** | returning, mixed devices | browses heavily, converts on discount, skips upsell | natural cart variance |
| **Window Shopper** | new+returning, any device | high browse / low purchase | natural drop-off noise |
| **Old-Device Android** | Android 10–12, `device_age > 24mo` | **crashes more AND retains less — independently** | **carries the device-age confounder** |
| **Marketing-Spike Bouncer** | paid channel, acquired in a spike window | low intent, bounces at home/browse | **low-intent decoy cohort (noise, not a fault)** |
| **Slow-Network Intl** | non-home geo | higher baseline latency, occasional timeouts | latency variance |

The **Old-Device Android** persona is what makes the confounder real: at *baseline* (no fault) these users both crash more and churn more, so "crashers churn" is true but **not causal**. That's the trap the agent must resist.

## 1.3 The planted "gaps" (fault library) + severity ladder
Each instance plants **0 or 1 primary fault** on a cohort, at a severity from the ladder **2 / 4 / 8 / 16 pp** conversion impact:

| Fault | Mechanism | Signature |
| :-- | :-- | :-- |
| Dead/broken screen | a screen fails to load for a cohort | drop-off spike at that screen, cohort-specific |
| Checkout latency regression | p95 climbs on a segment | elevated latency events + correlated drop-off |
| Cold-start regression | home never renders | `app_open` with no `home_view`, cohort-specific |
| Crash concentration | **incremental** crash spike on a device/OS cohort (above the Old-Device baseline) | crash events + suppressed return, *beyond* baseline |
| Payment-provider failure | one payment method silently fails | `payment` with no `order_confirmed` for that method |

**Instance types (the anti-tautology machinery):**
- **Clean-fault** instances — one fault, clear cohort. Baseline scoring.
- **Confounder-trap** instances — **no planted fault**, but Old-Device users crash+churn at baseline. Correct answer = "no actionable fault; device-age is the driver." Flagging crashes = **false positive**. This is the confounder-resistance test.
- **Simpson** instances — one segment silently improves while another regresses; aggregate conversion looks flat. Tests whether the agent segments before concluding.
- **Decoy** pressure — every instance has the upsell/tutorial drop-offs present; flagging one is a false positive.

## 1.4 Data-exposure contract (NO LEAKAGE — the load-bearing rule)

The agent must never receive any field that encodes the answer. Enforcement is **physical**, not honor-system: two separate stores per instance.

**AGENT-VISIBLE — `warehouse_<id>.duckdb`** (exactly what a real production analytics warehouse would contain — nothing more):
```
events: user_id, session_id, event_ts, event_name (raw/cursed), screen,
        os, device_type, device_age_months, geo, channel, is_returning,
        latency_ms?, is_crash, payment_method?, props(JSON)
users:  user_id, os, device_type, device_age_months, geo, channel,
        is_returning, acquired_ts
```
The agent's `run_sql` tool connects **only** to this DB. It must rediscover cohorts from these real attributes.

**SCORER-ONLY — `ground_truth_<id>` (a separate store the agent code cannot import/connect to):**
```
persona_map:  user_id → persona          # our narrative construct — NEVER exposed
gold:         the golden answer record (§1.8)
```

**Why each visible column is allowed:** `os / device_type / device_age_months / geo / channel / is_returning / latency_ms / is_crash / payment_method` are all genuine telemetry a real app collects — and `device_age_months` in particular MUST stay visible or the agent could never *correctly* attribute the device-age confounder. **Hidden:** `persona` (our label = a shortcut to the answer) and the entire gold/manifest.

**Leakage design-check:** no single visible attribute may perfectly identify a fault cohort. Because personas are overlapping *distributions* (not disjoint partitions), the affected cohort is a realistic predicate (e.g. `os='Android 12' AND device_age_months>24`) that also contains non-fault users. Verify this per instance — if one raw column cleanly separates fault from non-fault users, that's leakage; perturb the persona mix until it doesn't.

## 1.9 Document corpus (the RAG surface — load-bearing, not flavor)

The agent cannot separate symptom from mechanism, or fault from decoy, without knowing what the product is *supposed* to do. Generate the corpus alongside the data. It is **static across all instances** (one product, one dictionary — realistic and far less work); only the event stream + planted faults vary per instance.

| Artifact | Visibility | Role |
| :-- | :-- | :-- |
| `spec/prd.md` | agent-visible | intended behaviour per screen, the funnel, **which steps are optional** (decoy signal), SLOs, supported payment methods |
| `taxonomy/events.jsonl` | agent-visible | ~300 **cursed** event names — the `resolve_events` retrieval surface |
| `spec/tickets/*.md` | agent-visible | a few synthetic support tickets — retrieval noise + realism |
| `ground_truth/event_canonical_map.json` | **scorer-only** | `raw_name → canonical_logical_event` gold for event-resolution P/R |

**Two rules that keep the corpus honest:**
1. **Describe the healthy, *intended* product — never the fault.** PRD: "checkout should feel instant", "the upsell interstitial is optional; users may skip it." It never says "checkout is slow on Android 12." Intent is fair; the bug is not. (Same principle as hiding `persona` — expose the signal, never the answer.)
2. **The taxonomy mess must be answer-neutral, and the generator must actually *emit* the cursed names.** ~40–50 canonical logical events, each with 1–4 surface aliases (casing/spelling variants), some marked deprecated-but-firing, some firing-but-undocumented. The generator picks among aliases when writing `event_name`, so the agent sees `chkout_init` in the warehouse and **must** resolve it via the dictionary. Staleness/incompleteness must NOT correlate with which event is faulty.

**Design notes:** the decoy-resistance capability depends on the agent retrieving the PRD's "optional" line; the latency/cold-start capabilities depend on retrieving the intended SLOs. Keep **quantitative conversion baselines OUT** of the PRD — SLOs like "p95 < 2s" belong there, but "checkout converts at 85%" does not; the agent derives baselines from the data. The hidden `event_canonical_map` is generated as a by-product of taxonomy generation (you know the canonical event before you scramble its aliases).

## 1.8 The golden evaluation set (generate the questions WITH the data)

Each instance ships a **task** given to the agent + a **held-out gold answer** used only by the scorer. This is the eval-first spine: questions and correct answers exist before the agent runs.

**Task prompt given to the agent** (neutral — must NOT leak whether a fault exists, nor the cohort/mechanism):
> "Review the conversion funnel for [period]. Identify the root cause(s) of any regression — the mechanism, the affected user cohort as an explicit predicate, and the evidence. **If there is no actionable fault, say so.**"

The prompt may state the *symptom* an analyst would genuinely see (e.g. "retention dipped week-over-week") because in reality the dashboard shows *where* — the task is to find *why*. It must be **symmetric** across fault and confounder-trap instances, so confounder-trap instances still present a plausible surface symptom (old-device churn dips retention) whose correct resolution is "not an actionable fault."

**Gold answer record (held out):**
```python
class Gold(BaseModel):
    instance_id: str; seed: int
    has_fault: bool                         # False for confounder-trap instances
    fault_type: str                         # or "none"
    affected_user_ids: list[str]            # for cohort-F1
    affected_cohort_predicate: str          # human-readable, for the judge
    severity_pp: float
    confounder_type: str                    # e.g. "device_age", "low_intent", "simpson"
    is_confounder_trap: bool
    decoy_screens: list[str]
    acceptable_mechanisms: list[str]        # what the scorer accepts as "correct"
```

**Question variants (optional, per instance-type — finer capability signal, same data):**
- *Attribution* (every instance): the neutral prompt above.
- *Confounder probe* (trap instances): correct answer = "no actionable fault; device-age is the driver." Flagging crashes = false positive.
- *Decoy probe*: "Users drop off at the upsell screen — is this worth fixing?" → gold: no, by design.

Keep the **attribution task identical across all instances** so A/B/C are compared apples-to-apples; add probes only as extra per-capability signal.

## 1.5 Hypothesis output (agent → scorer/UI contract)
```python
class Evidence(BaseModel): claim: str; sql: str; result_summary: str
class Hypothesis(BaseModel):
    mechanism_type: Literal["dead_screen","checkout_latency","cold_start",
        "crash_concentration","payment_failure","innocent_dropoff"]
    mechanism: str
    affected_cohort: str          # constrained SQL WHERE over whitelisted cols
    evidence: list[Evidence]
    confidence: float
    confounders_considered: list[str]
```
Cohort predicate = SQL `WHERE` over whitelisted columns (`os, device_type, device_age_months, geo, channel, is_returning`) → compiled to a user-ID set for cohort-F1 scoring.

## 1.6 Generation mechanics
Layered, **seeded**, reproducible generator:
1. **Population** — sample N users across the persona mix (persona proportions per instance).
2. **Behaviour** — per user: latent intent → session arrivals over ~14 sim-days (weekday/weekend seasonality) → funnel transitions conditioned on persona/attributes → per-event latency/crash/cold-start draws → raw (cursed) event names.
3. **Fault injection** — modify the affected cohort's parameters; **calibrate the modification so realised conversion delta hits the target pp** (sweep param → measure → pin the mapping).
4. **Two-store output** — write (a) `warehouse_<id>.duckdb` with the **agent-visible** tables only (no `persona`), and (b) the **scorer-only** `ground_truth_<id>` store holding the `persona_map` + the `Gold` record (§1.8). The agent path can reach (a) only; (b) is never importable/connectable from agent code. Run the **leakage design-check** (§1.4) before accepting an instance.

**Design checks (run these — they catch tautology):** confirm Old-Device users churn more whether or not they crashed (confounder is real); confirm Simpson configs actually reverse under segmentation; confirm severity lands within ±1pp of target.

## 1.7 Sizes
5–10k users/instance → ~0.5–2M events. Dev instances ~2k users. Generate **8 dev + up to 50 full**; the gate agent-run uses ~24, scale to 50 post-gate.

---

# Deliverable 2 — Testbench UI (run + compare the solutions)

**Primary purpose:** an internal workbench to run System A/B/C on a generated case and **compare their outputs against ground truth**. Secondary: the demo payload. Stack: **React/Next (designed in Paper) + FastAPI**, per the project decision.

## 2.1 Screens
1. **Case Library** — generated instances; each card: persona mix, severity, seed, and a **dev-mode ground-truth reveal** (planted fault + affected cohort). Pick a case.
2. **Funnel Overview (the symptom)** — conversion by step; the drop-off highlighted; **segment by persona/attribute**. This view is 100% mine — needs only the data, not the agent.
3. **Run panel** — pick System **A / B / C** (or all three) → Run → **SSE stream** of the investigation. For C, render the live **Falsifier loop** (hypothesis → evidence → kill-attempt → revision).
4. **Hypotheses** — ranked root-cause cards per system: mechanism, affected cohort (+ resolved user count), evidence (SQL + numbers), confidence, confounders considered.
5. **Comparison / Scoring (the heart)** — A vs B vs C side by side, each with the scorer's verdict vs ground truth: top-1 correct? cohort-F1? decoy FP? confounder resisted? Live metrics. **This is "test the different solutions."**
6. **Roadmap brief** — the downstream demo artefact.

## 2.2 API (FastAPI)
`GET /cases` · `GET /case/{id}/funnel` (segmentable) · `POST /analyze {case_id, system}` → **SSE** step stream + final `Hypothesis[]` · `GET /score/{run_id}` (scorer vs manifest). **Manifest stays server-side; never sent to the agent path** — only the scorer + dev-reveal read it.

## 2.3 Build order (don't block on the agent)
The agent-dependent part is only screen 3+4. Build the rest first against a **mock agent**:
1. Case Library + Funnel Overview + Scoring view → **data + scorer only, real, unblocked.**
2. Mock `/analyze` returning canned `Hypothesis[]` → build Run + Hypotheses + Comparison against the mock.
3. Swap the mock for Shubham's real agent via the §0 contract.

---

## 3. My day-by-day (18 → 22 Jul)

| Day | Data (Deliverable 1) | UI (Deliverable 2) |
| :-- | :-- | :-- |
| **18 (today)** | Sync §0 contract w/ Shubham. Finalize product + personas + fault library. Generator skeleton. | Kick off **Paper design** of the 6 screens. |
| **19** | Generator core: personas → baseline events → 1 clean instance in DuckDB. Funnel analytics queries. | — |
| **20** | Fault library + confounder-trap + Simpson + severity ladder + manifest. Generate dev(8)+full set. **Scorer.** | — |
| **21** | Freeze data. Run design checks (§1.6). | UI build: FastAPI + React/Next from Paper. Case Library + Funnel + Scoring on real data; mock agent for Run/Hypotheses. |
| **22 (gate)** | Support integration. | Wire Shubham's real agent → Comparison view. Polish. Demo. |

**If a day slips:** protect the data + scorer + Funnel + Comparison views (they carry the thesis); the live Falsifier animation and roadmap tab are the deferrable polish.

---

## 4. Assumptions (correct me)
- You own data-gen **and** the scorer (they're the same "is it right?" surface). If Shubham owns the scorer, drop it from my list.
- The UI is primarily a **dev testbench**, secondarily the demo — so ground-truth reveal in dev-mode is fine (agent never sees it).
- Persona-driven generation (named personas) over pure statistical distributions — your call "different personas of users."
