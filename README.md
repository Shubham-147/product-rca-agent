# product-rca-agent

Product Discovery Copilot — root-cause attribution for product funnels. Given a
product spec, an event taxonomy, and a raw event stream, produce ranked
root-cause hypotheses (mechanism + affected cohort + evidence + confounders
ruled out), evaluated against planted faults with a blinded manifest.

## Repository layout

| Path | Owner | What it is |
| :-- | :-- | :-- |
| `simulator/` | Vinay | Persona-driven benchmark generator. Per instance, writes an **agent-visible** DuckDB warehouse (real telemetry only) + a **scorer-only** ground-truth store. Cursed event taxonomy, 5 faults + decoys + confounders + Simpson + severity ladder, leakage guards. |
| `eval/` | Vinay | Scorer (compiles the agent's cohort predicate to a user set; scores cohort-F1 / top-1 / decoy-FP vs held-out gold), a naive baseline system, and a runnable case harness. |
| `docs/` | Vinay | Project brief, execution plan, data + UI plan, generated-data overview (with a worked example), UI plan. |
| `data/` | Vinay | Generated instances — **git-ignored**, reproducible from seeds. |
| _agent_ | Shubham | Systems A (vanilla RAG) / B (Pydantic AI ReAct) / C (LangGraph + Falsifier). |

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m simulator.generate --n 24 --users 8000 --seed 1000   # generate the benchmark
python -m simulator.inspect_instance --id inst_003             # peek at one case (agent's view)
python -m eval.run_case --id inst_001                          # run + score one test case
python -m eval.run_case --all                                  # score all cases (naive baseline)
```

## System A — simple Vanilla RAG

System A is intentionally non-agentic. It performs one fixed evidence pass using the
same event resolver, analytics compiler, warehouse, spec retrieval, contracts, model
configuration, and tracing as B/C, followed by one structured generation call. The
model receives no tools and cannot adaptively query the data.

```bash
# Uses the shared RCA_LLM_BASE_URL / RCA_LLM_API_KEY / RCA_MODEL_NAME settings.
python -m scripts.run_system_a --id inst_001
python -m eval.run_suite --system A --workers 4
```

System A and System B also share the same suite runner and output layout:

```bash
python -m eval.run_suite --system A --workers 4
python -m eval.run_suite --system B --workers 4
```

## System C — LangGraph multi-agent + falsifier

System C keeps System B's typed, read-only analytics tools but splits reasoning between
an investigator and an adversarial falsifier. LangGraph runs a bounded cyclic graph:
the investigator proposes one RCA, the falsifier tries to disprove it with fresh tool
calls, and a rejected proposal returns for one evidence-driven revision.

```bash
# Uses the same RCA_LLM_BASE_URL / RCA_LLM_API_KEY / RCA_MODEL_NAME settings as System B.
python -m scripts.run_system_c --id inst_001 --max-cycles 2
python -m eval.run_suite --system C --workers 1
```

See [docs/system-c.md](docs/system-c.md) for the architecture, every implementation
change, configuration, failure behavior, and verification commands.

## Comparison API

The root-level FastAPI service reads the existing A/B/C suite manifests and exposes
one UI-ready endpoint. It never runs models or changes evaluation data.

```bash
.venv/bin/uvicorn api.app:app --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/comparison
```

The endpoint returns aggregate metrics followed by case-aligned A/B/C predictions.
For a UI on another origin, set `COMPARISON_UI_ORIGINS` to a comma-separated allowlist;
localhost and `127.0.0.1` ports 3000 and 5173 are allowed by default.
See [docs/comparison-api.md](docs/comparison-api.md) for the response contract and
failure behavior.

## React workbench

The `frontend/` Vite application recreates the three-column investigation workbench
using live data from `GET /comparison`: case library, system comparison, per-case A/B/C
results, scorer verdicts, and run telemetry.

```bash
# Terminal 1
.venv/bin/uvicorn api.app:app --host 127.0.0.1 --port 8000

# Terminal 2
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. See [frontend/README.md](frontend/README.md) for API URL
configuration.

The corresponding manifests are `eval/results/suite_system_<A|B|C>.json`; readable
traces are written below `eval/traces/`. See [docs/system-a.md](docs/system-a.md) for
System A's shared-foundation boundary.

## The integration contract (agent ↔ benchmark)

An agent/system is any callable `run(warehouse, task) -> list[Hypothesis]`. Plug it
into the harness with `python -m eval.run_case --all --system <module>`. The three
interfaces to match:

1. **Event schema** — the DuckDB `events` / `users` tables the agent queries.
2. **`Hypothesis`** output schema — [`simulator/schemas.py`](simulator/schemas.py).
3. **The task/question** — `data/tasks/task_<id>.json` (+ human-readable `data/TASK.md`).

The agent must never see `data/ground_truth/` (persona map, gold, canonical event
map) — that is the scorer's only. See [`docs/generated-data-overview.md`](docs/generated-data-overview.md)
for the full design and a worked end-to-end example (`inst_001`).
