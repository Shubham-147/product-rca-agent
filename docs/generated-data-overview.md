# The Benchmark Dataset — What Was Generated & How It Is Used

**Component:** `simulator/` (owned by Vinay) · **Project:** Product Discovery Copilot — root-cause attribution for product funnels · **Status:** v0, runnable & verified (2026-07-18)
**Related:** [project-brief.md](project-brief.md) · [data-and-ui-plan.md](data-and-ui-plan.md) · [simulator/README.md](../simulator/README.md)

---

## 1. At a glance

We generate a **benchmark**, not just a dataset. Each *instance* is a matched pair:

> **(what the agent sees)** — a realistic event warehouse + a product spec + a messy event dictionary + a neutral question
> **(held out from the agent)** — the golden answer: which fault was planted, in which exact users, at what severity.

The agent is graded on faults **it has never seen**. Because *we* generated the users, we know exactly which user IDs each fault touched — so the metrics are objective, not fuzzy.

A current sample run (`--n 20 --users 8000 --seed 1000`) produced:

| | |
| :-- | :-- |
| Instances | **20** (mix of 5 fault types, confounder-traps, a Simpson case) |
| Total events | **~5.07 million** (~250k events / ~7,500 users per instance) |
| Event taxonomy | **~225 firing names → 201 documented**, mapping to ~40 canonical events |
| Ground-truth records | one `gold_<id>.json` + `persona_<id>.json` per instance + one shared `event_canonical_map.json` |
| Reproducibility | fully seeded — same seed reproduces every byte |

**Mental model for the instances:** the 20 are **statistically-independent snapshots of the
*same* product** — same PRD, funnel, and event dictionary every time, but each with its own
freshly-sampled user population (disjoint user IDs) and **at most one** planted fault. Not "20
different companies" (the product is fixed) and not "one company with 20 stacked issues" (the
populations are disjoint and each run has ≤1 fault). Holding the product fixed and varying only
the fault + population is what makes each result attributable to the agent.

---

## 2. What was generated (the artifacts)

```
data/
├── corpus/                          ← AGENT-VISIBLE, static across all instances
│   ├── spec/prd.md                  intended behaviour of every screen (never mentions a fault)
│   ├── spec/tickets/*.md            synthetic support tickets (retrieval noise)
│   └── taxonomy/events.jsonl        the "cursed" data dictionary (~201 entries)
│
├── warehouses/                      ← AGENT-VISIBLE, one per instance
│   ├── warehouse_inst_000.duckdb    events + users tables (NO persona, NO canonical event)
│   ├── … inst_019.duckdb
│   └── index.json                   instance list (ids only)
│
└── ground_truth/                    ← SCORER-ONLY, never reachable from agent code
    ├── gold_inst_000.json           the held-out answer for each instance
    ├── persona_inst_000.json        user_id → persona (our narrative label)
    ├── event_canonical_map.json     surface_name → canonical (event-resolution answer key)
    └── index.json                   all answers, for reporting
```

The split into two directories is the **central integrity mechanism** (§6). Everything under `warehouses/` and `corpus/` is what a real analytics stack would expose; everything under `ground_truth/` is knowledge that only the person who *built the simulation* could have.

---

## 3. What the agent is given (the three inputs)

### 3.1 The event warehouse (`warehouse_<id>.duckdb`)
A DuckDB database with two tables — exactly the shape a product analytics warehouse has:

- **`events`**: `user_id, session_id, event_ts, event_name, screen, os, device_type, device_age_months, geo, channel, is_returning, latency_ms, is_crash, payment_method`
- **`users`**: one row per user with the same attribute columns + `acquired_ts`

`event_name` uses the **messy real-world names** (see 3.3), not clean ones. There is **no `persona` column and no `canonical` column** — those would hand the agent the answer.

### 3.2 The product spec (`spec/prd.md`)
Describes what each of ~15 screens is *supposed* to do — the funnel, the intended SLOs ("checkout should feel instant, p95 < 2s"), and crucially **which steps are optional** ("the upsell interstitial is optional; a high drop-off there is by design"). This is what lets the agent tell a real fault from an innocent drop-off. It never names a fault.

### 3.3 The cursed event taxonomy (`taxonomy/events.jsonl`) — the RAG surface
Real event taxonomies are a mess, so ours is too. A single logical event like *checkout-start* fires in the data under **seven different surface names**:

```
evt_chkout_init · ChkoutInit · CheckoutStart · begin_checkout · chckt_strt · BeginCheckout · track_start_checkout
```

The dictionary has inconsistent casing, deprecated-but-still-firing names, ~30 firing-but-undocumented names, and ~6 documented-but-dead entries. This is what makes "which events are relevant to this hypothesis?" a genuine **retrieval problem with a measurable precision/recall**, rather than a dictionary lookup.

---

## 4. What is held back (the golden answer)

Each instance ships a `gold_<id>.json`. Here is a real one (crash fault on old Android devices):

```json
{
  "instance_id": "inst_003",
  "has_fault": true,
  "fault_type": "crash_concentration",
  "affected_user_ids": [ … 562 user IDs … ],
  "affected_cohort_predicate": "os = 'Android 12' AND device_age_months > 24",
  "severity_pp_target": 8.0,
  "severity_pp_realised": 11.0,
  "is_confounder_trap": false,
  "is_simpson": false,
  "decoy_screens": ["upsell", "tutorial"],
  "acceptable_mechanisms": ["crash_concentration"],
  "changepoint_day": 14,
  "notes": "Old-Device persona crashes+churns at baseline (standing device-age confounder)."
}
```

Plus two more held-out files:
- **`persona_<id>.json`** — the true persona of every user (our narrative label).
- **`event_canonical_map.json`** — the correct canonical event for all ~225 surface names; the answer key for scoring event resolution.

---

## 5. The users (personas) and what they encode

Users are generated from six personas — each an attribute profile plus a behavioural model. Personas are how heterogeneity and, more importantly, **confounders** are baked in structurally rather than bolted on.

| Persona | Who they are | Role in the benchmark |
| :-- | :-- | :-- |
| Loyal Converter | new flagship devices, high intent | healthy baseline |
| Bargain Hunter | mixed devices, discount-driven | natural cart variance |
| Window Shopper | high browse, low purchase | natural drop-off noise |
| **Old-Device Android** | Android 10–12, device >2yrs | **crashes AND churns at baseline — the device-age confounder** |
| **Marketing-Spike Bouncer** | paid acquisition, low intent | **the innocent decoy cohort (looks like a problem, isn't)** |
| Slow-Network Intl | non-home geo, high latency | latency variance |

The **Old-Device Android** persona is the intellectual crux: with *no fault at all*, these users both crash more and convert less. So "crashers churn" is a true correlation that is **not** causal — a naive system will mis-attribute churn to crashes when the real driver is device age. That trap is what separates a real attribution engine from a plausible-story generator.

---

## 6. The no-leakage boundary (why this is trustworthy)

The whole benchmark is worthless if the agent can peek at the answer. Two examples of leakage we prevent:

- **The `persona` label** — "Old-Device Android" *is* the answer to "which cohort?". If the agent could `GROUP BY persona`, it would win by cheating. So `persona` lives only in the scorer-only store; the agent must **rediscover** the cohort from real signals (`os`, `device_age_months`).
- **The `canonical` event** — if the data told the agent that `chckt_strt` means *checkout-start*, event resolution would be free. So the canonical mapping is the held-out answer key.

Enforcement is **physical, not honour-system**: the agent connects only to `warehouse_<id>.duckdb`, which does not contain these columns. A build-time guard (`checks.assert_no_leak`) fails generation if a forbidden column ever appears — and we verified it actually catches an injected `persona` (it does).

---

## 7. The faults, decoys, and confounders (what there is to find)

Each instance plants **at most one primary fault**, at a severity from a **2 / 4 / 8 / 16 percentage-point ladder**, always against a backdrop of decoys and confounders.

| Fault | Where it hides | Signal it leaves | Realised severity (4/8/16pp targets) |
| :-- | :-- | :-- | :-- |
| Dead screen | a device cohort | `api_error` + drop at product page | ~3 / 9 / 17 pp |
| Checkout latency | a device cohort | high checkout latency + abandonment | ~2 / 9 / 16 pp |
| Cold-start | old-OS cohort | `app_open` with no `home_view` | ~2 / 6 / 17 pp |
| Crash concentration | old-device cohort | crash-rate spike (e.g. 1.6% vs 0.1%) | crash-rate rise, tracks target roughly |
| Payment failure | one payment method | `payment` with no `order_confirmed` | ~4 / 11 / 15 pp |

Always present alongside:
- **Decoys** — the optional upsell / skippable tutorial genuinely shed users. Flagging one is a **false positive**, and is scored as such.
- **Confounder-trap instances** — *no fault is planted*; the old-device correlation and a post-changepoint traffic-mix shift produce a surface dip whose correct answer is **"no actionable fault — device age / low-intent traffic is the driver."**
- **Simpson instances** — one segment silently improves while another regresses, so the aggregate looks flat; the agent must segment before concluding.
- **The severity ladder** turns the headline result from pass/fail into a **detection-vs-severity curve** ("reliable at ≥8pp, degrades below 4pp") — impossible to fabricate and far more informative.

Severity is measured as the drop at the *affected step* (which has full headroom), so 4/8/16pp calibrate close to target; 2pp deliberately sits at the noise floor, which is the honest thing for the curve to show.

---

## 8. How this will be useful (mapped to each consumer)

### 8.1 For the agent (Shubham's `product-rca-agent`)
The warehouse + corpus **are the agent's entire input surface**, and the `Hypothesis` schema in [simulator/schemas.py](../simulator/schemas.py) is the exact output contract. The agent's tools map 1:1 onto the artifacts: `retrieve_spec` reads the PRD, `resolve_events` searches the taxonomy, `run_sql` queries the warehouse. Nothing about his agent needs to change if he builds against these three interfaces.

### 8.2 For evaluation (the scorer — BUILT and runnable)
A test case = `tasks/task_<id>.json` (the question) + the warehouse + corpus,
scored against `gold_<id>.json`. Run it:

```bash
python -m eval.run_case --id inst_003     # one case, shows question + output + score
python -m eval.run_case --all             # every case, summary table
```

The `--system` is pluggable — today it defaults to a **naive baseline** (looks
only at the clean `is_crash`/`latency_ms` columns; cannot resolve cursed event
names). On the 20-case set it scores:

```
attribution top-1: 6/17 fault cases | mean cohort-F1: 0.389 | false positives: 0
```

i.e. it nails checkout-latency (F1 ~0.97) and crash (~0.85), correctly says
"no fault" on all three confounder-traps, and is blind to dead_screen /
cold_start / payment_failure because it never resolves event names. **That gap is
the project's whole thesis** — the real agent, with RAG event-resolution + SQL
reasoning, is what must beat this. Swap Shubham's agent (or systems A/B/C) in via
`--system <module>`, where the module exposes `run(warehouse, task) -> list[Hypothesis]`.

Every metric in the brief has a direct source in `gold`:

| Metric | Fed by |
| :-- | :-- |
| Attribution top-1 / recall@3 | `fault_type` + `acceptable_mechanisms` |
| **Cohort-ID F1** | `affected_user_ids` (compile the agent's cohort predicate → user set → set overlap) |
| False-positive rate on decoys | `decoy_screens` + `is_confounder_trap` (`has_fault=false`) |
| Confounder resistance | the trap + Simpson instances |
| Detection-vs-severity curve | `severity_pp_realised` across the ladder |
| Event-resolution P/R | `event_canonical_map.json` |

Because the affected users are an exact set, cohort accuracy is a hard number, not a judgement call.

### 8.3 For the testbench UI
- **Case Library** ← `warehouses/index.json` (+ `ground_truth/index.json` in dev-mode to reveal the planted fault).
- **Funnel Overview** ← the warehouse alone (the `inspect_instance.py` script already computes this "symptom" view).
- **Comparison/Scoring** ← run A/B/C on a case, score each against `gold`, show side-by-side.

### 8.4 For the project's thesis
The dataset is engineered to *prove* the three claims the project rests on:
1. **Retrieval ≠ attribution** — a vanilla-RAG baseline can retrieve a chunk mentioning "checkout" but cannot compute that checkout is slow; the aggregation-heavy faults expose this.
2. **Correlation ≠ causation** — the Old-Device confounder makes a naive system confidently wrong.
3. **Symptom ≠ mechanism** — "users drop at checkout" restates the chart; "checkout p95 is 4.2s on this exact cohort of 8,400 users" is the mechanism, and only the second matches the gold.

---

## 9. Worked example — one task, end to end (`inst_001`)

A single test case, traced with its real data. `inst_001` planted a **checkout-latency
fault on iOS 17** (~9.5pp impact, 2,445 affected users) — but the agent is told none
of that.

### 9.0 The runtime access model
One case = **one warehouse + the shared corpus + one question**. The agent is handed
exactly one `warehouse_<id>.duckdb`; it never sees the other instances. The corpus
(PRD + dictionary) is shared and static — it's one product's documentation. The harness
loops over cases *outside* the agent.

```
 tasks/task_inst_001.json ─┐
 warehouses/…inst_001.duckdb ─┼─► SYSTEM.run(warehouse, task) ─► list[Hypothesis] ─┐
 corpus/ (PRD + dictionary) ─┘        (reason → query → resolve → conclude)         │
                                                                                    ▼
                              gold_inst_001.json (held out) ──► scorer.score_case() ──► metrics
```

### 9.1 What the task file contains (input contract)
`tasks/task_inst_001.json` points the agent at its data and states the question. It
carries **no** fault, cohort, or answer — those live in the held-out gold. Key fields:
`warehouse` (the one DuckDB to query), `corpus.prd` / `corpus.taxonomy` (retrieval
surface), `changepoint_day: 14` (baseline days 0–13 vs recent 14–27),
`cohort_whitelist_columns` (the only columns a cohort predicate may use).

### 9.2 How the agent works the case (real numbers)
1. **Find where users drop** (SQL): a regression localises to the checkout → payment step.
2. **Resolve cursed event names** (RAG): all of these raw names in the data are the same
   logical event, resolved via the dictionary —
   `evt_chkout_init · BeginCheckout · ChkoutInit · CheckoutStart · begin_checkout · track_start_checkout → checkout_start`.
   A naive keyword match miscounts here; this is the retrieval capability under test.
3. **Segment to find who** (SQL): checkout→payment conversion for iOS 17 falls
   **82.7% → 73.4%** (≈9.3pp, matching the planted severity).
4. **Name the mechanism, not the symptom** (SQL + PRD): checkout-screen p95 latency by OS —
   iOS 17 jumps **1294 ms → 4778 ms** (2.4× the PRD's `< 2000 ms` SLO) while Android 14
   stays flat (1298 → 1269 ms). The PRD is what makes "4.8s" a *defect* rather than a number.
5. **Rule out confounders and emit** a `Hypothesis`:
   `mechanism_type="checkout_latency"`, `affected_cohort="os = 'iOS 17'"`, evidence, confidence,
   `confounders_considered=["device age","traffic-mix shift"]`.

### 9.3 How it is scored
The scorer compiles the claimed predicate against the warehouse —
`SELECT DISTINCT user_id FROM users WHERE os = 'iOS 17'` — to a concrete user set, then
compares to gold's 2,445 planted IDs:
- mechanism `checkout_latency` == gold ✓
- **cohort-F1 = 0.972** (precision 0.945, recall 1.0)
- **top-1 correct** ✓ (mechanism matches AND F1 ≥ 0.5 floor)

### 9.4 The actual run
```
$ python -m eval.run_case --id inst_001
agent output: [('checkout_latency', "os = 'iOS 17'")]
score: top1_correct=True, cohort_f1=0.972, precision=0.945, recall=1.0
```
Swap the baseline for any real system with `--system <module>` (exposing
`run(warehouse, task) -> list[Hypothesis]`) and nothing else changes.

---

## 10. Reproducing it

```bash
source .venv/bin/activate                # Python 3.10; deps in simulator/requirements.txt
python -m simulator.generate --n 24 --users 8000 --seed 1000 --out data
python -m simulator.inspect_instance --id inst_003
```

Generation is deterministic: `instance_id → seed`. The taxonomy is built from a fixed seed and is identical across every run. Delete `data/` and regenerate to get byte-identical output.

---

## 11. Current state & honest limitations

**Working & verified:** end-to-end generation, the two-store no-leakage boundary (with an active guard), the cursed taxonomy + canonical map, all five faults, decoys, the three confounders, the Simpson setup, and the severity ladder.

**Still to tune (iterative):**
- 2pp severity is at the sampling-noise floor and can read slightly negative — expected, and what the detection curve is meant to reveal; more users tightens it.
- Crash severity is reported as a crash-*rate* rise and tracks the pp target only loosely (it is the "weakest, most interesting" metric by design).
- Cohorts are single-column predicates today; compound/harder cohorts are a natural extension.
- Taxonomy is ~225 firing names; can be pushed toward ~300.

**Now built too:** the task/question (`data/TASK.md`, `data/tasks/task_<id>.json`), the scorer (`eval/scorer.py`), a runnable case harness (`eval/run_case.py`), and a naive baseline system to exercise it.

**Not yet built (separate deliverables):** the testbench UI, the richer metrics (LLM-judge, event-resolution P/R harness), and Shubham's real agent (A/B/C).
