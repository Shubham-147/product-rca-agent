# System A — thin shared-foundation Vanilla RAG

## Refactor record

System A was consolidated into `agent/systems/system_a.py`. The duplicate
`agent/system_a/` package was removed in full: its loader, schema, preprocessing,
retrieval, LLM client, execution, metrics, pipeline, and package initializer. The
standalone `scripts/evaluate_system_a.py` and redundant `SystemAReadme.md` were also
removed. `scripts/run_system_a.py` now calls the shared `SystemA` adapter directly,
and all-system evaluation remains in `eval/run_suite.py`.

The explicit System-A-only `openai` and `python-dotenv` dependency entries were
removed; model access and `.env` loading now come through the shared Pydantic-AI and
Pydantic Settings stack. FastAPI/Uvicorn remain for the root comparison API.

## Scope

System A is a deliberately constrained baseline implemented entirely in
`agent/systems/system_a.py`. It reuses the deterministic foundation beneath Systems B
and C, then makes one structured generation call. It has no agent loop, model-visible
tools, query decomposition, raw SQL generation, or falsification loop.

## Leakage boundary

Generation reads the selected task, its agent-visible warehouse, and the shared product
spec index. Only the shared suite scorer reads `data/ground_truth/`, after generation.

## Architecture

1. Open the task warehouse through shared `agent.warehouse.Warehouse`; raw event names
   are canonicalized by shared `agent.retrieval`.
2. Use shared `agent.analytics.Analytics` for an overall funnel, one-dimensional funnel
   slices, and fixed mechanism metrics across `os`, `device_type`, `geo`, `channel`,
   and `is_returning`.
3. Make one query against shared `agent.retrieval.spec` for PRD/SLO context.
4. Serialize that fixed evidence bundle once (approximately 11k tokens on `inst_001`).
5. Make one structured Pydantic-AI generation call using shared configuration and the
   shared `AgentHypothesis`/`Cohort` contract.
6. Return the standard `RunResult`; the shared suite writes traces and scores it.

`agent/tools/` is not imported by System A. Those model-visible tools remain exclusive
to B and C.

## Commands

```bash
.venv/bin/python -m scripts.run_system_a --id inst_001
.venv/bin/python -m eval.run_suite --system A --workers 4
```

System A also implements the shared `agent.systems.base.System` contract through `agent/systems/system_a.py`. This makes its suite command and output folders identical to System B:

```bash
.venv/bin/python -m eval.run_suite --system A --workers 4
.venv/bin/python -m eval.run_suite --system B --workers 4
```

Suite manifests are written to `eval/results/suite_system_<A|B|C>.json` and readable
traces to `eval/traces/system_<A|B|C>_<instance>.md`. A, B, and C use the same `RCA_`
model configuration.

## HTTP API

System A no longer owns an HTTP service. The root-level `api/` package exposes saved
A/B/C comparison results to the UI through the single read-only `GET /comparison`
endpoint. System A execution and evaluation remain explicit CLI operations.

## Output schema

The output is the same typed `AgentHypothesis`/`Hypothesis` and `RunResult` contract
used throughout the repository. The trace records the fixed evidence pass, generation
messages, tokens, and latency.

## Assumptions and limitations

- Evidence is deliberately broad and fixed rather than adaptively investigated; this is
  the principal Vanilla RAG limitation.
- The model cannot interrogate the warehouse, validate confounders interactively, or
  recover evidence omitted by the one-shot bundle.
- Observational co-movement is reported as association, not proof of causality.
- Low-severity faults can be indistinguishable from noise; metrics must come from the completed offline run and must never be inferred from design mockups.
