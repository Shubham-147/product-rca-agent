# Execution Plan — Product Discovery Copilot (full scope, staged to a hard gate)

**Team:** Post Hoc (G1) — Vinay Kumar Agarwal, Shubham
**Gate:** 22 July 2026 — hard submission date. Today: 17 July.
**Strategy:** Keep **everything** in the brief. Nothing is cut. Stage it at the 22 Jul line: a self-contained **gradeable core** lands by the gate; the **depth tail** is sequenced right after and declared in-progress.
**UI:** React/Next designed in **Paper MCP** (design → code), FastAPI backend wrapping the agent.
**Companion docs:** [project-brief.md](project-brief.md), [Capstone-Design-Doc.pdf](Capstone-Design-Doc.pdf)

---

## 0. Staging model — nothing cut, everything sequenced

| Line | Contents |
| :-- | :-- |
| **Stage 1 — Gradeable Core (by 22 Jul gate)** | Full simulator w/ all anti-tautology machinery · cursed taxonomy + hybrid retrieval · Systems A/B/C · full objective metric suite · LLM-judge (evidence-faithfulness) · a real (thin) React/Next analyst-loop UI · docs + failure analysis + 3-min demo · agent eval run on a **gate batch (~24 instances)** |
| **Stage 2 — Depth & Polish (post-gate, shown in-progress at submission)** | Scale agent eval run to **full N=50** · judge **human-calibration on 30 samples** + agreement report · **Retailrocket** real-data sanity check · multi-fault "hard" subset scoring · UI polish (live Falsifier trace, cohort viz) · cost/latency deep report |

> Generation of all 50 instances is cheap (simulation code). What's expensive is *running the agents* over 50 × 3 systems. So we **generate the full set**, run the gate batch first, and expand the agent run in Stage 2.

**The two results the whole project exists to produce (protect above all):**
1. **A-vs-C** ≥30pp attribution gap (the pre-committed falsifiable claim).
2. **B-vs-C** — does multi-agent + Falsifier actually beat the single ReAct agent? If B ties C, that is an honest, shippable finding.

> Intellectual weight lives in the **simulator's confounders**, not the agents. Naive confounders → C "wins" by inverting the generator → hollow result. This gets real design time (§D).

---

## 1. Roles (doc's split + a UI track)

Two people, three workstreams. The UI is sequenced (it wraps a working agent), so nobody runs three tracks at once.

- **Track A — Simulator + Eval** (owner _TBD_): data generator, cursed taxonomy, fault/decoy/**confounder** library, blinded manifests, **scorer**. Owns "is the benchmark real?"
- **Track B — Agents** (owner _TBD_): retrieval surface + `resolve_events`, Systems A/B/C. Then **pivots to the UI build** once System C is stable (Day 4).
- **UI design (Paper):** a short focused design pass early (can be done together / with Claude via Paper MCP), so the build target exists before Track B pivots.
- **Shared:** failure analysis, docs, demo.

Default mapping (swap on strengths): stronger on **SQL/data/stats** → Track A; stronger on **LLM/agent frameworks + frontend** → Track B. Track A's confounder design is the single highest-leverage work in the project.

---

## 2. Frozen interface (TODAY, together, ~2–3h)

Highest-leverage task. Freeze end of Day 0.5; both tracks then build against stable contracts with mocks. Nothing here changes after today.

### 2.1 Event warehouse (DuckDB)
`events` table (denormalised for the agent's SQL tool) + a `users` dim table:
```
events: user_id, session_id, event_ts, event_name (raw/cursed), screen,
        os, device_type, device_age_months, geo, channel, is_returning,
        latency_ms?, is_crash, payment_method?, props(JSON), instance_id
users:  user_id, os, device_type, device_age_months, geo, channel,
        is_returning, acquired_ts, instance_id
```

### 2.2 Corpus (RAG surface)
- `spec/prd.md` — intended behaviour of ~15 screens/steps.
- `taxonomy/events.jsonl` — ~300 event names: aliases, dupes, inconsistent casing, deprecated-but-firing, partial/stale descriptions.
- `spec/tickets/*.md` — synthetic support tickets (retrieval noise).

### 2.3 Hypothesis output schema (Pydantic — agent↔scorer contract)
```python
class Evidence(BaseModel):
    claim: str
    sql: str
    result_summary: str

class Hypothesis(BaseModel):
    mechanism_type: Literal[            # closed set = scorable
        "dead_screen","checkout_latency","cold_start",
        "crash_concentration","payment_failure","innocent_dropoff"]
    mechanism: str                      # free-text testable claim
    affected_cohort: str                # constrained SQL WHERE (2.4)
    evidence: list[Evidence]
    confidence: float                   # 0..1
    confounders_considered: list[str]
```

### 2.4 Cohort-predicate language — constrained SQL `WHERE`
- Free `WHERE` over a **whitelisted column set only**: `os, device_type, device_age_months, geo, channel, is_returning`.
- Validate (parse + column whitelist) → compile to `SELECT DISTINCT user_id FROM users WHERE <predicate>` → exact user-ID set for F1.

### 2.5 Manifest + scorer contract
- `ground_truth/manifest_<instance_id>.json`: `{fault_type, severity_pp, affected_user_ids[], confounder_type, decoy_screens[], seed}`.
- Stored in a package the **agent code physically cannot import**. Only the scorer reads it. Blinding is load-bearing.
- Deterministic: `instance_id → seed`.

### 2.6 UI API contract (so the front end can be built against a mock)
- `GET /cases` → list of instances. `POST /analyze {case_id}` → **SSE stream** of graph node events (hypothesis → evidence → falsification attempt → revision → final ranked list + roadmap brief).
- `GET /result/{case_id}` → cached final result. **Manifest is never exposed** through the API.

---

## D. Data-generation design (called out because the data is the foundation)

A layered, seeded generator. Each layer is independently testable.

1. **Population model.** Sample user attributes from realistic marginals + deliberate correlations: `device_age_months` skews older on Android/low-cost devices; `channel` correlates with intent. These correlations are what make confounders *real*, not decorative.
2. **Behavioural model.** Per-user latent **intent**; session arrival process over ~14 sim-days (with weekday/weekend seasonality); funnel transition probabilities conditioned on attributes + intent. Emits the raw event stream with per-event latency draws, cold-start times, crash draws.
3. **Fault-injection layer.** For the planted fault, modify the relevant parameter **for the affected cohort only** (e.g. checkout p95 latency ↑, crash prob ↑, a screen's load-success ↓, a payment method's success ↓), calibrated so the **downstream conversion impact hits the target pp** on the severity ladder (2/4/8/16pp). Calibration is empirical: sweep the parameter, measure realised pp, pin the mapping.
4. **Decoy + confounder structure** (baked into baseline, not injected as "faults"):
   - **Decoys:** optional upsell / skippable tutorial with a genuinely high, *by-design* drop-off. Flagging one = false positive.
   - **Confounders (3):** (a) device-age → *both* higher crash rate *and* lower retention, independently (crash is a passenger); (b) a low-intent marketing-spike cohort that bounces (fault-*looking* non-fault); (c) **Simpson config** — one segment silently improves while another regresses so aggregate conversion looks flat.
5. **Noise layer.** Seasonality + the low-intent cohort as background variance the agent must see through.
6. **Manifest writer + seed.** Records exactly which user IDs the fault hit, severity, confounder type, decoy screens. Fully reproducible.

**Design checks (do these, they catch tautology):** confirm the confounder is statistically real (crashers *and* non-crashers on old devices both churn more); confirm the Simpson config actually reverses under segmentation; confirm severity calibration lands within ±1pp of target.

---

## 3. Day-by-day to the gate

Sync 15 min at start + end of each day. Tracks run parallel against §2 mocks.

### Day 0.5 — TODAY (17 Jul)
- **Both:** `git init`, scaffold (`sim/ agents/ eval/ ground_truth/ spec/ taxonomy/ ui/ docs/`), **freeze §2 interface**, seed strategy, model + **cost ceiling**.
- **Track A:** finalize the §D generation design.
- **UI:** kick off the Paper design of the analyst loop (case picker · funnel view · live investigation/Falsifier panel · ranked root-cause cards · roadmap brief). Can be produced with Claude via Paper MCP.

### Day 1 — 18 Jul
- **Track A:** generator core (population + behavioural + baseline) → one clean fault-free instance in DuckDB.
- **Track B:** retrieval surface — cursed-taxonomy loader, `resolve_events` (**hybrid BM25 + dense + cross-encoder rerank**) + **P/R harness** proving hybrid > dense-only. Stub System A (vanilla RAG).

### Day 2 — 19 Jul
- **Track A:** fault library (5) + decoys + 3 confounders + Simpson + **severity ladder** + manifest writer. **FREEZE taxonomy + fault library today.** Generate dev set (8) + full set (50).
- **Track B:** **System B** (Pydantic AI ReAct) — tools `retrieve_spec`, `resolve_events`, `run_sql` (DuckDB), `cohort_stats`. Validated `Hypothesis` objects on the dev set.

### Day 3 — 20 Jul
- **Track A:** **scorer** — full objective suite (§5) from planted IDs. Select the gate batch (~24).
- **Track B:** **System C** (LangGraph) — HypothesisGen → EventResolver → SQLAnalyst → Validator → **Falsifier** → ReportWriter. Falsifier back-routes to revise; **cap 2–3 iterations + no-new-evidence stop.**

### Day 4 — 21 Jul
- **Track A:** run **A/B/C** on the gate batch → comparison table, **detection-vs-severity curve**, confounder-resistance split. Wire the **LLM-judge** (evidence-faithfulness, cross-family model).
- **Track B:** pivot to UI — **FastAPI** wrapping System C (SSE per §2.6) + **React/Next** front end from the Paper design (design-to-code skill). Thin but real analyst loop end-to-end.

### Day 5 — 22 Jul (GATE)
- **Both:** integrate UI + results; **failure-analysis** write-up (attempts/failures/pivots — a real grading lever); docs (4–5pp); README w/ repro; **3-min demo video**. Submit the gradeable core + declare Stage-2 items in-progress.

### If a day slips
Protect in order: cohort-ID F1 + top-1 (≥12 instances) → A-vs-C → B-vs-C → decoy FP-rate → severity curve → UI. The UI is real but it's the most deferrable of the core (it wraps work that already exists); slip it into Stage 2 before you slip a metric.

---

## 4. Stage 2 — depth tail (post-gate)

1. Scale agent eval run to **full N=50** (+ the ~4 two-fault "hard" instances scored separately).
2. **Judge human-calibration:** 30 human-labelled samples, report judge–human agreement (don't assume the judge).
3. **Retailrocket** real-data sanity check — run the final system on one real, unlabelled clickstream; report survival, unscored.
4. UI polish: live Falsifier trace animation, cohort visualisations, confounder explainer, roadmap-brief tab.
5. Cost/latency deep report per architecture.

---

## 5. Metrics (full suite — all kept)

**Objective (the grade):** attribution top-1 (≥60%) & recall@3 (≥85%) · **cohort-ID F1** (≥0.80 @ ≥8pp) · decoy FP-rate (≤15%) · confounder resistance (reported) · **detection-vs-severity curve** (2/4/8/16pp) · event-resolution P/R (≥0.85) · tool-call accuracy (≥90%) · cost/latency per case.

**Qualitative:** LLM-judge evidence-faithfulness (1–5 rubric, cross-family model) · cause-vs-symptom rate · judge–human agreement (Stage 2).

**Scoring rule:** top-1 correct iff `mechanism_type` matches planted fault AND cohort-F1 ≥ 0.5. Partial-credit bands: F1 ≥0.8 full · [0.5,0.8) partial · <0.5 miss. Report strict + lenient.

---

## 6. Resolved defaults (brief §12)

1. **Population/volume:** 5–10k users/instance, multi-session over ~14 sim-days → ~0.5–2M events. Cohort (~10–15% of users) must leave a few hundred+ users at the affected step so 8pp is detectable at p<0.01 while 2pp is genuinely hard. Dev instances ~2k users.
2. **N:** dev 8; full 50 generated; gate agent-run ~24; Stage-2 agent-run 50.
3. **Fault co-occurrence:** 1 primary fault/instance for clean scoring; ~4 two-fault "hard" instances scored separately (Stage 2).
4. **Confounders:** the 3 in §D.4.
5. **Cohort language:** constrained SQL `WHERE`, whitelisted columns (§2.4).
6. **Attribution scoring:** §5.
7. **Judge:** strong cross-family model for judging; cheap model for high-volume event resolution; 1–5 evidence-faithfulness rubric; human calibration in Stage 2.
8. **Real dataset:** Retailrocket, Stage 2. License check when reinstated.
9. **Budget:** hard total ceiling + per-case cap (agree Day 0.5). Cheap model for drafts + event resolution, strong for Falsifier + judge. Cost/case logged (reported metric).
10. **Repro:** one seed/instance; manifest in an agent-unimportable package; scorer sole consumer; seeded generation reproduces exactly.

---

## 7. Standing risks (watch daily)
- **Tautology** (#1) — blinding + decoys + confounders + severity ladder. Run the §D design checks; weak confounders = hollow result.
- **Falsifier non-termination** — hard iteration cap + no-new-evidence stop.
- **Simulator scope creep** — taxonomy + fault library FROZEN end of Day 2.
- **Three-workstream overload** — the UI is *sequenced*, not parallel; don't start its build before System C is stable.
- **Gate pressure** — the "if a day slips" ladder (§3) is the pressure valve; use it early.

---

## 8. Tech surface (satisfies "use as many things as we can")
RAG: ChromaDB, hybrid BM25 + dense + cross-encoder rerank. Agents: Pydantic AI (B). Multi-agent: LangGraph cyclic graph (C). Warehouse: DuckDB. Eval: custom objective scorer + LLM-as-judge (cross-family). Models: cheap tier for event resolution/drafts, strong tier for Falsifier + judge (mix providers deliberately). UI: React/Next (Paper design→code) + FastAPI + SSE. Rejected on purpose (scores on reasoning): GraphRAG/Neo4j.
