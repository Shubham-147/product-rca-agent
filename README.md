# Product Discovery Copilot

Product Discovery Copilot is a research system for **attribution under confounding**, not
recommendation. Given a product symptom such as “checkout abandonment spiked,” it resolves
a messy event taxonomy, queries behavioral data, proposes root causes, and tests whether
the evidence supports them. The project compares a deliberately weak RAG baseline with a
tool-using agent and a cyclic multi-agent pipeline that actively tries to falsify its own
claims.

## Table of contents

- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Data and ground truth](#data-and-ground-truth)
- [Retrieval](#retrieval)
- [Root-cause systems](#root-cause-systems)
- [Evaluation](#evaluation)
- [What's stubbed / what's real](#whats-stubbed--whats-real)
- [Repository map](#repository-map)
- [Next steps](#next-steps)
- [Build log](#build-log)

## Architecture

The same generated taxonomy and event stream feed all three systems. The blinded manifest
is isolated from retrieval and system code and is opened only by the evaluation metrics.

```text
                         ┌──────────────────────────────┐
                         │ Blinded manifest             │
                         │ planted faults + user IDs    │
                         └──────────────┬───────────────┘
                                        │ eval only
                                        ▼
Stub Generator ──┬──> Taxonomy JSON ──> Hybrid Retrieval ──┐
                 │      BM25 + dense + reranker            │
                 │                                         ├──> System A: vanilla RAG ──┐
                 └──> Events CSV ──> DuckDB SQL ────────────┼──> System B: ReAct + tools ├──> Eval Harness ──> LLM Judge
                                                           └──> System C: LangGraph loop ┘
```

System C contains the only cyclic control flow:

```text
hypothesis_gen → event_resolver → sql_analyst → validator → falsifier
      ▲                                                       │
      └──────── revision + disconfirming evidence ────────────┤
                                                              ▼
                                                            report
```

LangGraph is used specifically because the Falsifier must carry state backward to
hypothesis generation. A forward-only chain or DAG cannot express that revision edge.

## Quick start

Create an environment and install dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Generate the deterministic stub data and build DuckDB:

```bash
.venv/bin/python scripts/generate_stub_data.py
.venv/bin/python -m src.retrieval.db
```

Run the offline demos and test suite:

```bash
.venv/bin/python scripts/run_system_a.py
.venv/bin/python scripts/run_system_b.py
.venv/bin/python scripts/run_system_c.py
.venv/bin/python -m src.eval.harness
.venv/bin/python scripts/run_judge.py
.venv/bin/python -m pytest -q
```

Offline demos use deterministic test doubles and make no paid model calls. For real OpenAI
calls, copy the template and add a key:

```bash
cp .env.example .env
# Set OPENAI_API_KEY in .env
```

`OPENAI_MODEL` defaults to `gpt-4o-mini`. Credentials and model selection are loaded only
through `src.config.get_settings()`; they are never hardcoded in system modules.

## Data and ground truth

The Phase 1 stand-in creates 65 deliberately inconsistent taxonomy entries and a 750-user,
roughly 15-step funnel. It includes snake case, camelCase, abbreviations, alias clusters,
and dead events that are defined but never fire. The event stream plants five fault types:

- shipping dead screen;
- checkout latency;
- cold-start suppression of home rendering;
- device/OS-specific crash;
- payment-provider failure.

It also contains an intentional promo-skip decoy and an old-device/OS confounder. The
generator is fixed-seed and reproducible. `data/manifest.json` records planted user IDs,
expected events, and severity metadata separately from the observable data. Retrieval and
systems never read it; only `src/eval/metrics.py` does.

The stub is intentionally smaller than the real simulator: the **full fault library is
N≈50 randomized faults + Simpson's paradox configs + severity ladder — this stub
implements a minimal subset to unblock Phase 2/3**. The generator is a replaceable
placeholder, not the completed Phase 1 simulator.

### DuckDB event schema

DuckDB provides an embedded, zero-infrastructure analytical surface. At this scale it
avoids operating Postgres while retaining typed SQL and fast local aggregation.

| Column | Type | Meaning |
| --- | --- | --- |
| `user_id` | `VARCHAR` | Synthetic user identifier |
| `session_id` | `VARCHAR` | Synthetic session identifier |
| `timestamp` | `TIMESTAMPTZ` | UTC event time |
| `event_name` | `VARCHAR` | Canonical or alias event name |
| `screen` | `VARCHAR` | Funnel screen or context |
| `category` | `VARCHAR` | Taxonomy category |
| `device_tier` | `VARCHAR` | Old, mid, or new device cohort |
| `os` | `VARCHAR` | Operating-system cohort |
| `cold_start` | `BOOLEAN` | Whether the session began cold |
| `latency_ms` | `BIGINT` | Added latency for performance events |
| `payment_provider` | `VARCHAR` | Assigned payment provider |
| `outcome` | `VARCHAR` | Event result or planted-fault symptom |

`src.retrieval.db.run_sql()` returns query results as pandas DataFrames and is the SQL tool
used by agentic systems.

## Retrieval

Event resolution uses the full hybrid pipeline:

```text
BM25 candidates ∪ dense candidates → deduplicate → cross-encoder rerank → top-k
```

BM25 protects lexical evidence in irregular aliases. For example, `chkout_init` is
lexically close to `checkout_start` but can be semantically invisible to embeddings.
Dense retrieval adds conceptual recall, Chroma stores vectors, and the cross-encoder
reranks the combined candidate set in the context of the original query. Dense-only
retrieval is therefore not accepted as the sole taxonomy strategy.

Real dense retrieval uses sentence-transformers (`all-MiniLM-L6-v2` by default), while
real reranking uses `cross-encoder/ms-marco-MiniLM-L-6-v2`. Select backends in `.env`:

```text
EMBEDDING_BACKEND=fake                 # or sentence-transformers
RERANKER_BACKEND=fake                  # or cross-encoder
```

Run the checked alias benchmark with:

```bash
.venv/bin/python scripts/benchmark_retrieval.py
```

## Root-cause systems

All systems emit the shared, Pydantic-validated `Hypothesis` schema: mechanism, affected
cohort, evidence, confounders ruled out, and confidence.

### System A — vanilla RAG baseline

System A retrieves taxonomy text, stuffs it into one prompt, and asks for a hypothesis. It
has no SQL, aggregation, cohort computation, or validation. This weakness is intentional:
**retrieval is not aggregation**. It may find relevant words but cannot establish which
users experienced a fault. Its affected cohort is narrative rather than query-grounded,
establishing the floor that Systems B and C must beat.

### System B — Pydantic AI ReAct agent

System B follows **reason → tool call → observe → repeat** with three tools:

- `retrieve(query)` for stub spec/taxonomy chunks;
- `resolve_events(query)` for hybrid taxonomy resolution;
- `run_sql(query)` for DuckDB aggregation.

Pydantic AI validates the final `Hypothesis`. This is a correctness boundary: malformed
output could otherwise silently corrupt user IDs or the evidence attached to a cohort.
Production construction uses the OpenAI settings from `.env`; the offline demo uses
Pydantic AI's deterministic function model while still executing real retrieval and SQL.

### System C — cyclic LangGraph pipeline

System C separates hypothesis generation, event resolution, SQL analysis, validation,
falsification, and reporting into stateful nodes. Falsification concretely means looking
for an intended decoy, a common-cause confounder, or a relationship that disappears or
reverses after stratification—a Simpson's-paradox-style failure. Disconfirmed evidence is
attached to graph state before control loops backward. `max_iterations` prevents infinite
revision; exhausting the cap produces an explicit ruled-out result.

In the checked scenario, the Falsifier rejects “old hardware directly causes crashes”
after finding that crashes concentrate in Android 10, then reports the 25 SQL-grounded
crashing users after one revision.

## Evaluation

The Phase 4 harness runs all systems over five planted faults and one decoy, then saves
`data/eval_results.csv`.

| Metric | Definition | Target |
| --- | --- | --- |
| Attribution top-1 / recall@3 | Leading hypothesis names the planted mechanism | ≥70% |
| Cohort-ID F1 | Set F1 of reported versus planted user IDs | ≥70% |
| Cause-vs-symptom rate | Answer names a mechanism instead of echoing the symptom | ≥90% |
| Decoy false-positive rate | Intended behaviors incorrectly called faults | ≤10% |
| Confounder resistance | Confounded cases surviving stratified falsification | ≥70% |
| Event-resolution precision/recall | Resolved versus expected taxonomy events | ≥80% / ≥80% |
| Tool-call accuracy | Set F1 of selected versus required tools | ≥90% |
| Cost per case | Mean model and tool spend | ≤$0.10 |
| Latency per case | Mean end-to-end runtime | ≤30 seconds |
| Detection vs severity | Attribution at 2/4/8/16pp effects | ≥40/60/75/90% |

The falsifiable commitment rule is: **“System C beats System A by ≥30pp on attribution
accuracy.”** The evaluator prints `SYSTEM C WINS` or `SYSTEM C LOSES` from that rule and
does not reinterpret an underperforming result.

### Evidence-faithfulness judge

The LLM judge grades a single answer using this fixed rubric:

1. **1** — The narrative is contradicted by, or unrelated to, the cited numbers and does not disclose limitations.
2. **2** — The narrative has weak numerical support, makes major unsupported causal leaps, or omits major unresolved alternatives.
3. **3** — The narrative partially follows from the cited numbers but contains a material gap, ambiguity, or incomplete limitation disclosure.
4. **4** — The narrative follows from the cited numbers with only minor gaps and discloses the important factors it could not rule out.
5. **5** — The narrative is fully supported by the cited numbers, clearly separates observation from inference, and explicitly discloses what it could not rule out.

**Judge–human agreement is reported, not assumed.** The five-row placeholder calibration
reports 80% exact agreement and Pearson `r=0.959`. Those figures validate wiring only;
real calibration requires approximately 30 human-labelled samples.

## What's stubbed / what's real

| Component | Current status | Replacement path |
| --- | --- | --- |
| Event/taxonomy generator | **Stub**: 750 users, five faults, one decoy, one confounder | Replace with Phase 1's full N≈50 randomized fault simulator, Simpson configurations, and severity ladder |
| `FakeEmbeddingClient` | **Test-only fake**: deterministic feature-hashed vectors | Set `EMBEDDING_BACKEND=sentence-transformers` |
| `FakeReranker` | **Test-only fake**: deterministic lexical heuristic | Set `RERANKER_BACKEND=cross-encoder` |
| `FakeLLMClient` | **Test-only fake**: canned deterministic completion | Inject `OpenAIClient` with `.env` credentials |
| Pydantic AI function model | **Test-only fake model loop** | Construct `SystemB()` with its configured OpenAI model |
| Human calibration labels | **Stub**: five illustrative rows | Collect and adjudicate ≈30 real human-labelled samples |
| Taxonomy retrieval, Chroma indexing, DuckDB queries | **Real implementation** over stub data | Retain interfaces; rebuild indexes/database from Phase 1 data |
| Systems A/B/C orchestration | **Real implementation** | Replace test model dependencies, not orchestration |
| Quantitative metrics and commitment verdict | **Real implementation** | Run over the full blinded benchmark |

Fakes are selected explicitly through configuration or dependency injection; production
code does not silently fall back to them.

## Repository map

```text
data/                  generated taxonomy, events, DuckDB, blinded truth, results
scripts/               reproducible generators, benchmarks, and system demos
src/config.py          centralized environment settings
src/generator/         deterministic Phase 1 stand-in
src/retrieval/         DuckDB, BM25, dense search, reranking, hybrid resolver
src/systems/           shared schemas/client and Systems A, B, C
src/eval/              quantitative metrics, harness, qualitative judge
tests/                 offline acceptance and regression tests
```

## Next steps

1. Integrate the real Phase 1 simulator without changing retrieval/system interfaces:
   full N≈50 fault library, randomized severity ladder, richer decoys, and explicit
   Simpson's-paradox configurations.
2. Rebuild DuckDB, taxonomy indexes, and blinded evaluation cases from Phase 1 output.
3. Replace fake embeddings, reranker, and language models in non-test runs; add real token
   cost and latency telemetry.
4. Collect approximately 30 adjudicated human labels and recalibrate the qualitative judge.
5. Continue into **Phase 5** (experiment hardening, scale, and robustness) and **Phase 6**
   (productization, interfaces, observability, and deployment).

## Build log

| Step | Milestone | Delivered |
| ---: | --- | --- |
| 0 | Scaffold | Packages, settings, dependencies, environment template |
| 1 | Stub data | Messy taxonomy, event funnel, blinded planted-fault manifest |
| 2 | DuckDB | Typed embedded event table and DataFrame SQL helper |
| 3–5 | Retrieval | BM25, Chroma dense search, cross-encoder interface, hybrid resolver |
| 6 | LLM interface | Shared OpenAI and deterministic fake clients |
| 7 | System A | Vanilla RAG floor without aggregation |
| 8 | System B | Pydantic AI ReAct tools and validated output |
| 9 | System C | Cyclic LangGraph pipeline with Falsifier backward edge |
| 10 | Quantitative eval | Comparative metrics, severity curve, commitment verdict |
| 11 | Qualitative eval | Evidence-faithfulness judge and calibration mechanism |
| 12 | Consolidation | Contributor-oriented architecture and operating guide |
