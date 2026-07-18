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
