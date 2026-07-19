# Product Discovery Copilot — Root-Cause Attribution for Product Funnels

### Full Project Brief & Planning Handoff

**Team:** Post Hoc (G1) — Vinay Kumar Agarwal, Shubham **Context:** Capstone project, AI Engineering Cohort (RAG & Agents). 8-week syllabus culminating in a 10-day build (13–22 July 2026). **Purpose of this document:** A complete, self-contained brief. It captures *what* we are building and *why we made each decision*, so that a planning LLM (or a new collaborator) can pick it up cold and help produce an end-to-end execution plan. It deliberately does **not** prescribe the final task breakdown — that is the next step, and Section 12 lists the open questions a planner must resolve.

---

## 1\. One-paragraph summary

Product analytics tells a team **where** users drop off in a funnel; it never tells them **why**. We are building a system that takes a product specification, an event taxonomy, and a raw behavioural event stream, and produces a ranked set of **root-cause hypotheses** for a funnel regression — each naming the underlying **mechanism** (not the symptom), the **exact user cohort** affected, and the **evidence** — while correctly rejecting drop-offs that are innocent by design or merely correlated with the true cause. Because real root-cause labels do not exist in industry, we generate a controlled simulated environment with **planted faults and a blinded ground-truth manifest**, which lets us measure attribution accuracy objectively. We evaluate three architectures of increasing complexity (vanilla RAG, single ReAct agent, multi-agent pipeline) against each other and choose the simplest one that clears a pre-committed accuracy bar.

---

## 2\. The problem, in full

### 2.1 The gap we are closing

Every product team runs into the same wall. A dashboard shows that 40% of users abandon at the checkout step. The dashboard cannot tell them *why*. The cause could be any of:

- The checkout page has a latency regression (p95 climbed from 1.2s to 4.2s).  
- A payment method is silently failing on one OS version.  
- The app is crashing for a subset of users, and crashers don't return.  
- The cold-start time regressed, so the home screen never renders and users never reach checkout at all.  
- **Nothing is wrong** — the step is one users are *supposed* to skip (an optional upsell), and the "drop-off" is by design.

A human analyst resolves this by forming a hypothesis, querying the data, checking a cohort, ruling out confounders, and repeating. It is slow, it requires expertise, and it is exactly the loop an agent should be able to run.

The market is full of "AI product copilots" that generate a fluent narrative for that 40% number. **Almost none of them are evaluated on whether the narrative is true.** They produce plausible stories, not verified causes. That unmeasured gap — between *plausible* and *provable* — is the whole project.

### 2.2 The core intellectual claim (the thesis)

Analytics tells you **where** users leave, never **why**. Symptom detection is easy; **causal attribution under confounding** is the hard part, and it is the part every AI product copilot currently fakes.

Three sub-claims fall out of this, and each maps to something we must demonstrate:

1. **Retrieval is not attribution.** Retrieving a document chunk that *mentions* checkout does not tell you checkout is slow. Root-cause analysis is fundamentally an **aggregation** problem (counting, grouping, comparing cohorts over time), not a **retrieval** problem. A naive RAG system will fail at it, and we will prove this quantitatively — that proof is what licenses the added complexity of the agent systems.  
2. **Correlation is not causation.** "Crashers don't return" does not mean crashes cause churn — an old device may cause *both*, independently. A system that cannot distinguish these will confidently produce wrong root causes. Detecting and resisting confounders is the hardest and most interesting capability.  
3. **Symptom is not mechanism.** "Users drop off at checkout" is a restatement of the funnel chart. "Checkout p95 is 4.2s on Android 12, and the drop-off is concentrated in that exact cohort" is a mechanism. Only the second is actionable, and most systems only ever produce the first.

### 2.3 Precise problem statement

**Input to the system:**

- A **product specification / PRD** describing what each screen and funnel step is *supposed* to do (the agent cannot know a screen is broken without knowing its intended behaviour).  
- An **event taxonomy / data dictionary**: the catalogue of event names and their properties (deliberately messy — see Section 4.3).  
- A **raw behavioural event stream**: per-user, timestamped events across sessions (app opens, screen views, taps, crashes, latencies, purchases).

**Output of the system:**

- A **ranked list of root-cause hypotheses**. Each hypothesis is a structured object containing:  
  - `mechanism` — the causal explanation, stated as a testable claim.  
  - `affected_cohort` — an explicit, queryable predicate defining the affected users (e.g. `os = 'Android 12' AND device_age > 24mo`), resolving to a concrete user-ID set.  
  - `evidence` — the specific metrics, comparisons, and queries that support it.  
  - `confidence` — a calibrated score.  
  - `confounders_considered` — what alternative explanations were checked and ruled out.

**Explicitly out of evaluation scope:** roadmap and feature-prioritisation suggestions. There is no ground truth for "the correct roadmap," so grading generated suggestions against a rubric we authored ourselves would be circular. The system still *produces* a roadmap brief as a downstream artefact (it is the demo payload), but the **evaluated contract is attribution, not recommendation.** This separation is the single most important design decision in the project and should be preserved through planning.

---

## 3\. Why this shape (decision log)

This section records how we arrived here, so a planner understands which constraints are load-bearing and which are negotiable.

| Decision | Reasoning | Firmness |
| :---- | :---- | :---- |
| Evaluate **attribution**, not roadmap output | Roadmaps have no ground truth; grading them is circular and the cohort spec penalises vague problem statements. Attribution has hard, checkable labels. | **Firm** — this is the spine of the project. |
| Use a **simulator with planted faults** | Public repo required (no proprietary data), and real causal labels do not exist anywhere. Planted-fault benchmarking is the standard method in RCA / AIOps research. | **Firm** — but must be blessed by a mentor (see §11). |
| Keep the simulated product **tiny** (one funnel, \~15 screens) | The simulator is *infrastructure*, not the deliverable. Effort belongs in the agent and the eval, not in building a general product simulator. | **Firm.** |
| Build **three architectures**, baseline first | The cohort mandates a comparative evaluation of ≥2 approaches. Baseline-first also avoids the "complexity bias" failure mode the spec warns about. | **Firm.** |
| Give retrieval a **real job** (cursed event taxonomy) | It's a *RAG & Agents* cohort; an agent-only project underweights RAG. A messy 300-name taxonomy makes event resolution a genuine retrieval problem with its own P/R score. | **Firm** — but the taxonomy size (300) is tunable. |
| **Reject GraphRAG** | The real relationships here are *statistical*, not structural. A knowledge graph adds infra without improving attribution. Justifying the omission scores on "decision reasoning." | **Considered-firm** — revisit only if a concrete structural sub-problem emerges. |
| Add a **real-data sanity check** | Converts "he built a simulator that solves his own simulator" into "he built a simulator *and checked it against reality*." | **Recommended**, first to cut if time-constrained. |

**Rejected alternatives** (so nobody re-litigates them): version-aware SDK migration agent, financial-filings QA, multi-hop Wikipedia QA, clinical-trial matching, health-claim checking. All were dropped for one of two reasons: they required domain expertise we don't have (so we couldn't tell a good answer from a subtly wrong one), or they were narrow developer-infra tools with low general utility. This project has neither problem: anyone can understand a funnel, and we can check every answer against a label we planted.

---

## 4\. The simulator (data generation)

This is the foundation everything else stands on. If it's naive, the whole project collapses into tautology (see §9).

### 4.1 The product

A single mobile e-commerce app with one primary conversion funnel:

app\_open → home\_view → browse/search → product\_detail → add\_to\_cart

         → cart\_view → checkout\_start → payment → order\_confirmed

\~15 screens total. Include a few deliberately off-funnel screens (profile, wishlist, an optional upsell interstitial) so the funnel isn't the only thing in the data.

### 4.2 The user-journey generator

A script that simulates a population of users moving through the app across sessions, emitting a realistic event stream. It must model:

- **User heterogeneity**: device type, OS version, device age, geography, acquisition channel, new vs. returning.  
- **Baseline behaviour**: realistic per-step conversion rates, session frequency, return rates — *before* any fault is applied.  
- **Temporal structure**: multi-day activity, weekday/weekend seasonality, a cohort of users acquired via a marketing spike (low intent, high bounce — a noise source, not a fault).  
- **Technical signals**: per-event latency distributions, crash events tied to specific device/OS conditions, cold-start times.

The generator's realism is the project's main risk surface. It does **not** need to be photorealistic; it needs to be *rich enough that the faults aren't trivially separable* from the noise.

### 4.3 The event taxonomy (the RAG surface)

Deliberately **cursed**, because real-world taxonomies are:

- \~300 event names.  
- **Aliases / duplicates**: `checkout_start`, `begin_checkout`, `chkout_init` all meaning the same thing.  
- **Deprecated-but-still-firing** events.  
- **Inconsistent casing and property schemas** across events.  
- A data dictionary that is incomplete and partly stale.

This is what makes "which events are relevant to this hypothesis?" a real retrieval problem with a measurable precision/recall, rather than a dictionary lookup.

### 4.4 The fault library

Each generated product instance has zero or more faults planted from this library (non-exhaustive; expanding it is a planning task):

| Fault | Mechanism | Signal it should leave |
| :---- | :---- | :---- |
| Dead / broken screen | A screen fails to load for some users | Drop-off spike at that screen for the affected cohort |
| Checkout latency regression | p95 latency climbs on a segment | Elevated latency events \+ drop-off correlated in that segment |
| Cold-start regression | First-screen load time high → home never renders | app\_open without subsequent home\_view, cohort-specific |
| Crash concentration | Crashes on a device/OS cohort | Crash events \+ suppressed return rate in that cohort |
| Payment-provider failure | One payment method fails silently | payment\_start without order\_confirmed for that method |

### 4.5 Decoys and confounders (the part that makes it a benchmark, not a toy)

Without these, the agent merely inverts the generator. **These are load-bearing.**

- **Innocent drop-offs (decoys):** steps *designed* to shed users (optional upsell, skippable tutorial). Flagging one is a **false positive** and must be scored as such.  
- **Confounders:** a hidden common cause. E.g. old devices independently cause *both* higher crash rates *and* lower retention. A naive agent sees "crashers churn" and mis-attributes. The correct answer is "device age is the driver; the crash is a passenger."  
- **Simpson's paradox setups:** aggregate conversion looks flat while one segment is badly broken and another silently improved, cancelling out. Tests whether the agent segments before concluding.  
- **Noise:** weekday seasonality; a low-intent marketing-acquired cohort that bounces for reasons that are not faults.  
- **Effect-size ladder:** plant each fault at multiple severities (e.g. 2 / 4 / 8 / 16 percentage-point conversion impact). This turns the headline result from a pass/fail into a **detection-vs-severity curve** ("reliable above 8pp, degrades below 4pp"), which is impossible to fabricate and far more informative.

### 4.6 The blinded manifest

For each of N ≈ 50 generated instances, the generator writes a **ground-truth manifest** recording exactly which faults were planted, at what severity, affecting which user IDs. This manifest is **held out** — not read during agent development or tuning, and revealed only at scoring time. This blinding is what makes the evaluation honest; without it we would unconsciously tune the agent toward answers we already know.

---

## 5\. Architecture (three systems)

Built and evaluated in ascending order of complexity. **Baseline first is a hard rule** — it establishes the floor that justifies (or fails to justify) everything more complex.

### System A — Vanilla RAG (baseline)

- **Stack:** LangChain \+ ChromaDB.  
- **Flow:** chunk and embed the spec, data dictionary, and a sampled slice of events; retrieve on the question; generate an answer.  
- **Expectation:** it will fail, and *the failure is a result, not an embarrassment.* RCA is aggregation, not retrieval; a retrieved chunk mentioning checkout cannot reveal that checkout is slow. Quantifying this failure is the point.

### System B — Single ReAct agent

- **Stack:** Pydantic AI.  
- **Tools:** `retrieve_spec` (RAG over the PRD), `resolve_events` (hybrid retrieval over the 300-name taxonomy), `run_sql` (DuckDB over the event warehouse), `cohort_stats`.  
- **Flow:** iterative Reason → Act → Observe. Hypothesise, query, read result, refine.  
- **Why Pydantic AI here:** hypotheses are consumed downstream as *structured objects* that get compiled into SQL. Type-validated output is a correctness requirement, not a convenience — a malformed cohort predicate produces a silently wrong query.

### System C — Multi-agent pipeline

- **Stack:** LangGraph (orchestrator-worker with routing).  
- **Nodes:**  
  - **Hypothesis Generator** — proposes candidate causes from spec \+ funnel deltas.  
  - **Event Resolver (RAG)** — maps a hypothesis to the correct event names in the messy taxonomy.  
  - **SQL Analyst** — writes and runs cohort/funnel/time-series queries.  
  - **Statistical Validator** — effect size, significance, segment decomposition.  
  - **Falsifier / Critic** — *adversarial*: its only job is to **kill** the hypothesis by finding a confounder or an innocent explanation. On success, routes control **back** to revise.  
  - **Report Writer** — evidence-linked brief with explicit uncertainty.  
- **Why LangGraph here (the decisive reason):** the Falsifier routes control **backwards** (generate → validate → try-to-kill → revise → re-validate). That is a **cycle** over shared, typed state. Single-agent loops and DAG-only frameworks cannot express it. This is also the honest answer to "why not just Pydantic AI everywhere?" — we *do* use Pydantic AI for System B, and B-vs-C is one of our comparative evaluations. If B wins, we ship B.

The **Falsifier is the intellectual core.** Symptom detection is easy; actively trying to disprove your own finding is the capability every commercial copilot skips, and it is what earns the Week 6/7 marks.

---

## 6\. Evaluation methodology

Because we generated the users, we know **exactly which user IDs** each fault affected. This yields unusually hard, objective metrics.

### 6.1 Quantitative

| Metric | Definition | Target (System C) |
| :---- | :---- | :---- |
| Attribution — top-1 | Correct planted cause ranked first | ≥ 60% |
| Attribution — recall@3 | Correct cause in top 3 | ≥ 85% |
| **Cohort-ID F1** | Exact set overlap (precision/recall harmonic mean) between claimed affected users and planted cohort | ≥ 0.80 at ≥ 8pp effect |
| **Cause-vs-symptom rate** | Fraction of outputs naming a mechanism, not a symptom | ≥ 75% |
| False-positive rate on decoys | Innocent drop-offs wrongly flagged | ≤ 15% |
| Confounder resistance | Accuracy on confounded / Simpson's configs | Reported (expected weakest, most interesting) |
| Event-resolution P/R | Retrieval quality: right events chosen from 300 | ≥ 0.85 |
| Tool-call accuracy | Valid, executable, correctly-parameterised calls | ≥ 90% |
| Cost & latency | Tokens / USD / wall-clock per resolved case | Reported per architecture |
| Detection vs. effect size | Recall at 2/4/8/16pp | Reported as a curve |

*(Definitions to keep straight: **precision** \= of what you claimed, how much was right; **recall** \= of what was truly there, how much you found; **F1** \= their harmonic mean, which only rises if both do. **pp** \= percentage points, not percent.)*

### 6.2 Qualitative — LLM-as-a-Judge

- Single-answer grading against a **fixed 1–5 rubric** on **evidence faithfulness**: does the narrative actually follow from the numbers it cites, and does it disclose what it could *not* rule out?  
- The judge is itself validated: calibrate against \~30 human-labelled samples and **report judge–human agreement** rather than assuming the judge is correct. (This is the Week 7 lesson — measure your evaluator.)

### 6.3 The headline comparison (pre-committed)

System C must beat System A on attribution accuracy by **≥ 30 percentage points** to justify its cost and complexity. If it does not, we report that honestly and the simpler system wins.

Stating the falsification condition in advance is on-thesis: the project is about a system that tries to disprove itself.

---

## 7\. Framework & stack decisions (with reasoning)

| Component | Choice | Why | Rejected alternative |
| :---- | :---- | :---- | :---- |
| Event warehouse | **DuckDB** | Embedded, zero-infra, fast analytical scans over millions of rows, clean SQL surface for the agent's tool | Postgres (ops cost, no analytical benefit at this scale) |
| Vector store | **ChromaDB** | Small corpus; matches Week-2 stack; no hosted DB needed | Pinecone/Weaviate (overkill) |
| Retrieval | **Hybrid BM25 \+ dense \+ cross-encoder rerank** | `chkout_init` is lexically near `checkout_start` but semantically invisible to embeddings; hybrid \+ rerank provably beats dense-only on the cursed taxonomy | Dense-only (we will show it underperforming) |
| Single-agent framework | **Pydantic AI** (System B) | Type-safe validated structured outputs compiled into SQL | — |
| Multi-agent framework | **LangGraph** (System C) | Cyclic, stateful graph required by the Falsifier's back-routing | LangChain chains / DAG frameworks (can't cycle) |
| Graph retrieval | **Rejected** | Relationships here are statistical, not structural | Neo4j / GraphRAG |
| Judge | Strong model for judging; cheap model for high-volume event resolution | Cost control; cost-per-case is a reported metric | — |
| UI (optional) | Streamlit | Fast to build an analyst-loop demo | — |

---

## 8\. Deliverables (per cohort spec)

- **Design doc** (1–2 pp) — done, the one-pager.  
- **Public code repository** — reviewable.  
- **Documentation** (4–5 pp) — including a mandatory **failure analysis** section (attempts, failures, pivots).  
- **3-minute demo video** — walkthrough of the system and eval results.  
- **Optional UI** — a functional interface for the analyst loop.

---

## 9\. Risks & failure modes

| Risk | Why it matters | Mitigation |
| :---- | :---- | :---- |
| **Tautology** — agent just inverts our generator | The single biggest threat; a reviewer spots it in 30 seconds | Blinded manifests; N≈50 randomised configs; decoys; confounders; effect-size ladder. This mitigation is *load-bearing*, not optional. |
| **Sim-to-real gap** | Simulated data is cleaner than reality | Name it openly in the doc; run the unlabelled real-clickstream sanity check |
| **Simulator scope creep** | The simulator is a means, not the end; easy to over-invest | Freeze taxonomy \+ fault library at end of Day 2; hard cap on product size |
| **Weak/ mushy evals** | Fuzzy attribution → fuzzy metrics | Objective set-overlap metrics from planted IDs; tight LLM-judge rubric with human calibration |
| **Judge unreliability** | Who grades the grader? | Report judge–human agreement, don't assume it |
| **"Fabricated data \= zero" misread by a mentor** | The spec forbids fabricated *results* | Proactively flag the synthetic-with-planted-ground-truth approach to a mentor *before* building; cite planted-fault RCA benchmarking as precedent |

---

## 10\. Suggested execution shape (starting point, not final plan)

This is a sketch to seed planning, not a committed schedule. The 10-day window is 13–22 July.

| Days | Focus | Key outputs |
| :---- | :---- | :---- |
| 1–2 | Simulator | User-journey generator, event taxonomy, fault library, decoys/confounders, blinded manifests, N≈50 instances |
| 3 | Retrieval surface | Spec/PRD corpus; hybrid \+ rerank event resolution; event-resolution P/R harness |
| 4–6 | The three systems | A (baseline), B (ReAct/Pydantic AI), C (LangGraph multi-agent \+ Falsifier) |
| 7–8 | Evaluation | Full quantitative suite; LLM-as-judge; human calibration of the judge |
| 9 | Reality check \+ analysis | Real-clickstream run; failure-analysis write-up |
| 10 | Package | Documentation, README (attempts/failures/pivots), 3-min demo |

**Parallelisation note:** the two-person split that works is *one owns the simulator \+ fault library \+ eval harness*, the *other owns the three agent systems*, with failure analysis shared. The simulator and the agents have a clean interface (the event warehouse \+ taxonomy \+ spec), so they can progress in parallel once that interface is fixed on Day 2\.

---

## 11\. What a planner still needs to decide (open questions)

Hand these to the planning step explicitly:

1. **Event volume & population size.** How many users / events per instance to make faults detectable but not trivial? Needs a quick power-analysis intuition.  
2. **How many instances (N)?** 50 is a placeholder. Trade-off between statistical stability of metrics and generation/scoring cost.  
3. **Fault co-occurrence.** One fault per instance, or several? Multiple faults make attribution much harder (and more realistic) but complicate scoring.  
4. **Confounder catalogue.** Which specific confounders beyond device-age? Each one is a mini research problem.  
5. **Cohort-predicate language.** How does the agent express `affected_cohort`? Free-form SQL `WHERE`, a constrained DSL, or structured filters? Affects both tool design and scoring.  
6. **Attribution scoring rule.** What counts as a "correct" cause when the mechanism is right but the cohort is slightly off? Define partial credit precisely.  
7. **Judge model & rubric wording.** Exact rubric text; which model; how many human-labelled calibration samples.  
8. **Real dataset choice.** Retailrocket vs. the multi-category e-commerce behaviour dataset vs. another. Licence check required on Day 1\.  
9. **Token/cost budget.** OpenAI key is granted on design-doc approval; set a per-run and total budget, since cost-per-case is a reported metric.  
10. **Repo & reproducibility.** Seeded generation so results reproduce; how the blinded manifest is stored so it's auditable but not leaked into training/tuning.

---

## 12\. Glossary (for a fresh reader)

- **Root-cause attribution:** identifying the underlying mechanism behind an observed metric change, not just the metric change itself.  
- **Cohort:** a set of users defined by shared attributes/behaviour (e.g. "Android 12 users on devices \>2 years old").  
- **Confounder:** a hidden variable that causes two things to correlate without one causing the other.  
- **Simpson's paradox:** a trend that appears in aggregate reverses (or vanishes) when the data is segmented.  
- **Planted-fault benchmarking:** deliberately injecting known faults into a system to create ground-truth labels for evaluating a detector. Standard in RCA/AIOps research.  
- **Blinded manifest:** the held-out record of planted faults, not seen during development, used only for scoring.  
- **ReAct:** an agent pattern of interleaved Reasoning and Acting (tool calls) and Observing results.  
- **Falsifier:** our critic agent whose sole purpose is to try to disprove a candidate hypothesis.  
- **Precision / Recall / F1:** correctness of what you claimed / coverage of what was there / their harmonic mean.  
- **pp (percentage points):** absolute difference between two percentages (40% → 32% is 8pp).  
- **Hybrid retrieval:** combining keyword (BM25) and semantic (dense embedding) search, usually followed by a cross-encoder reranker.

---

## 13\. The one line to keep in view

We are building the layer of a Product Discovery Copilot that can be **held accountable** — one that turns *"users are dropping off at checkout"* into *"checkout p95 is 4.2s on Android 12, affecting these 8,400 users, and here is why it isn't just old devices"* — and we prove it works by scoring it against faults it has never seen.  
