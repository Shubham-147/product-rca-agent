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
- [Configuration](#configuration)
- [JSON API](#json-api)
- [Data and ground truth](#data-and-ground-truth)
- [Retrieval](#retrieval)
- [Root-cause systems](#root-cause-systems)
- [Evaluation](#evaluation)
- [Generated artifacts](#generated-artifacts)
- [What's stubbed / what's real](#whats-stubbed--whats-real)
- [Repository map](#repository-map)
- [Testing and troubleshooting](#testing-and-troubleshooting)
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

For a command-by-command operational walkthrough, see [`trailrun.txt`](trailrun.txt).

## Configuration

All configuration is environment-based. `src/config.py` loads the project `.env` and
raises a clear error when a real OpenAI client is requested without an API key.

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | none | Required only for `openai` execution mode |
| `OPENAI_MODEL` | `gpt-4o-mini` | Shared OpenAI and Pydantic AI model |
| `EMBEDDING_BACKEND` | `fake` | `fake` or `sentence-transformers` |
| `SENTENCE_TRANSFORMER_MODEL` | `all-MiniLM-L6-v2` | Real dense embedding model |
| `RERANKER_BACKEND` | `fake` | `fake` or `cross-encoder` |
| `CROSS_ENCODER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Real reranking model |
| `EVENTS_DB_PATH` | `data/events.duckdb` | Optional DuckDB override, mainly for tests |

`offline` mode is deterministic and makes no paid calls. `openai` mode uses these settings
for Systems A/B and qualitative judging. System C's current graph nodes remain
deterministic and data-driven in both modes.

The project uses `pydantic-ai-slim[openai]`: it provides the `pydantic_ai` package and
OpenAI provider without unrelated provider extras whose telemetry dependencies conflict
with Chroma.

## JSON API

FastAPI exposes the complete pipeline as structured JSON. There is no custom web UI;
Swagger is the interactive client.

```bash
.venv/bin/python -m uvicorn src.api:app --reload
```

- Swagger: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`
- Health check: `http://127.0.0.1:8000/health`

### Endpoints

| Method and path | Purpose |
| --- | --- |
| `GET /health` | Return `{"status":"ok"}` for liveness checks |
| `POST /execute` | Run selected systems for one symptom, optionally with evaluation/judging |
| `POST /execute/full` | Run A/B/C, comparative evaluation, and qualitative judging |

`POST /execute` parameters:

| Parameter | Required/default | Meaning |
| --- | --- | --- |
| `symptom` | **required** | Product symptom or root-cause question |
| `systems` | `a`, `b`, `c` | Repeatable system selection; all three are the default |
| `mode` | `offline` | Deterministic `offline` models or configured `openai` models |
| `regenerate_data` | `false` | Recreate stub files and rebuild DuckDB before execution |
| `include_evaluation` | `false` | Run the complete blinded comparative harness |
| `include_judge` | `false` | Attach a validated 1–5 score and rationale |
| `max_iterations` | `3` | System C revision cap, from 0 through 10 |

`POST /execute/full` requires `symptom`, accepts `mode`, `regenerate_data`, and
`max_iterations`, and always enables all systems, evaluation, and judging.

Example selected-system request:

```bash
curl -X POST \
  'http://127.0.0.1:8000/execute?symptom=Why%20did%20checkout%20abandonment%20spike%3F&systems=b&mode=offline&include_judge=true'
```

Example complete request:

```bash
curl -X POST \
  'http://127.0.0.1:8000/execute/full?symptom=Why%20are%20older%20Android%20users%20crashing%20before%20cart%3F&mode=offline'
```

Response shape (values abbreviated):

```json
{
  "symptom": "Why did checkout abandonment spike?",
  "mode": "offline",
  "setup": {
    "data_regenerated": false,
    "database_rebuilt": false,
    "generated_event_rows": null,
    "database_rows_loaded": null,
    "data_directory": "/absolute/path/to/data"
  },
  "results": [
    {
      "system": "System B",
      "hypothesis": {
        "mechanism": "...",
        "affected_cohort": ["user_0001"],
        "evidence": ["..."],
        "confounders_ruled_out": [],
        "confidence": 0.82
      },
      "ruled_out_reason": null,
      "grounded_in_query_results": true,
      "tool_calls": [],
      "state_trace": [],
      "judge": {"score": 4, "rationale": "..."},
      "latency_seconds": 0.01
    }
  ],
  "evaluation": null,
  "total_latency_seconds": 0.02
}
```

Missing data is generated automatically. `regenerate_data=true` forces a fresh fixed-seed
build. Invalid parameters return HTTP 422; runtime configuration and pipeline errors
return HTTP 400 with a `detail` message. Requests are synchronous, so `/execute/full` is a
batch endpoint rather than a low-latency serving path.

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

Chroma persists its local index under `data/chroma/`. That directory is ignored by Git;
one process-wide client lets FastAPI worker threads safely reuse the same collections.

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

Current deterministic-stub snapshot:

| System | Attribution | Cohort F1 | Decoy FPR | Confounder resistance |
| --- | ---: | ---: | ---: | ---: |
| System A | 0% | 0% | 100% | 0% |
| System B | 100% | 100% | 100% | 0% |
| System C | 100% | 100% | 0% | 100% |

The current commitment verdict is `SYSTEM C WINS` with a 100-percentage-point margin.
These values describe the small deterministic stub, not expected production performance.

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

## Generated artifacts

| Path | Produced by | Contents |
| --- | --- | --- |
| `data/taxonomy.json` | `scripts/generate_stub_data.py` | Event definitions, aliases, descriptions, dead-event flags |
| `data/events.csv` | `scripts/generate_stub_data.py` | Synthetic user-level event stream |
| `data/manifest.json` | `scripts/generate_stub_data.py` | Blinded planted faults, cohorts, expected events, severities |
| `data/events.duckdb` | `python -m src.retrieval.db` | Typed local `events` table; ignored by Git |
| `data/chroma/` | Dense retrieval | Persistent local vector index; ignored by Git |
| `data/retrieval_benchmark.json` | `scripts/benchmark_retrieval.py` | Dense-only versus hybrid alias results |
| `data/system_a_demo.json` | `scripts/run_system_a.py` | Ungrounded baseline hypotheses |
| `data/system_b_demo.json` | `scripts/run_system_b.py` | ReAct hypotheses and tool traces |
| `data/system_c_trace.json` | `scripts/run_system_c.py` | Full cyclic graph state trace |
| `data/eval_results.csv` | `python -m src.eval.harness` | Comparative metric table |
| `data/judge_calibration.json` | checked fixture | Placeholder human/judge calibration labels |
| `data/judge_results.json` | `scripts/run_judge.py` | Qualitative scores and rationales |

Regeneration overwrites the fixed-seed taxonomy, events, and manifest. Evaluation code may
read the manifest; retrieval and Systems A/B/C must not.

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
trailrun.txt            command-by-command local execution runbook
src/api.py              FastAPI, Swagger, JSON execution endpoints
src/config.py          centralized environment settings
src/generator/         deterministic Phase 1 stand-in
src/retrieval/         DuckDB, BM25, dense search, reranking, hybrid resolver
src/systems/           shared schemas/client and Systems A, B, C
src/eval/              quantitative metrics, harness, qualitative judge
tests/                 offline acceptance and regression tests
```

## Testing and troubleshooting

Run the complete suite:

```bash
.venv/bin/python -m pytest -q
```

The current suite contains 29 passing tests covering configuration, generation, DuckDB,
retrieval, reranking, all three systems, evaluation, judging, and FastAPI/OpenAPI behavior.
Tests are offline and do not require `OPENAI_API_KEY`.

Common issues:

- **`python` not found:** use `.venv/bin/python` as shown in every command.
- **Missing generated files:** run `scripts/generate_stub_data.py`.
- **Missing `events.duckdb`:** run `python -m src.retrieval.db` with the venv Python.
- **Missing OpenAI key:** use `mode=offline`, or populate `.env` before real calls.
- **Model-hub access unavailable:** retain `EMBEDDING_BACKEND=fake` and
  `RERANKER_BACKEND=fake`.
- **Chroma/LangGraph/OpenTelemetry warnings:** current dependencies emit upstream
  deprecation or disabled-telemetry warnings under Python 3.14; warnings are not failures
  when pytest or the requested command exits successfully.
- **Slow `/execute/full`:** it synchronously runs all systems, all benchmark cases, and the
  judge. Use `/execute` with selected systems for interactive requests.

For the exact fresh-run order and expected outputs, use [`trailrun.txt`](trailrun.txt).

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
| 13 | JSON API | FastAPI execution endpoints, Swagger contract, worker-safe Chroma persistence |
