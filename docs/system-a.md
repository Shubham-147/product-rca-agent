# System A — Vanilla RAG

## Scope

System A is a deliberately constrained baseline: deterministic loading and event preprocessing, fixed-size chunks, a `text-embedding-3-small` dense vector index, exactly one vector query, and exactly one structured LLM call. It has no agent loop, tools exposed to the model, query decomposition, multi-query retrieval, HyDE, reranking, SQL generation, or falsification loop.

## Leakage boundary

Generation may read only `data/tasks/`, `data/corpus/`, and the selected database in `data/warehouses/`. Loader guards reject paths containing `ground_truth`, `gold`, or `persona`, and warehouse columns are checked for `persona`, `canonical`, fault labels, and affected-user labels. Each prediction and retrieval trace is saved before evaluation begins.

Only `scripts/evaluate_system_a.py` imports the existing gold loader. It refuses to open any gold file unless predictions for every indexed case already exist and validate. Ground truth therefore cannot influence ingestion, retrieval, the prompt, or generation.

## Architecture

1. Load the task, PRD, taxonomy, and support tickets with path checks.
2. Read the selected DuckDB warehouse once and aggregate it deterministically in pandas. The model does not generate or execute SQL.
3. Convert the telemetry aggregates into a source-labelled evidence document.
4. Chunk all allowed documents using a stable content-derived chunk ID.
5. Embed all chunks and the single query in one batched `text-embedding-3-small` request, then rank chunks by cosine similarity.
6. Send the top 12 chunks to one OpenAI structured-output call.
7. Validate the `SystemAOutput`/`Hypothesis` schemas and ensure cited chunk IDs were retrieved.
8. Persist prediction and trace JSON.
9. In a separate command, load held-out gold and calculate aggregate metrics.

## Commands

```bash
.venv/bin/python -m scripts.run_system_a --id inst_001
.venv/bin/python -m scripts.run_system_a --all
.venv/bin/python -m scripts.evaluate_system_a
```

The pipeline automatically loads `OPENAI_API_KEY` and `OPENAI_MODEL` from the repository-root `.env` file. Values explicitly supplied in the shell environment take precedence. There is intentionally no mock or heuristic generation fallback. Artifacts are written below `artifacts/system_a/`.

## Metrics API

Start the local service with `.venv/bin/python -m scripts.serve_system_a`. Then choose whether to reuse artifacts or regenerate them by sending the required boolean:

```bash
curl -X POST http://127.0.0.1:8000/system-a/metrics \
  -H 'Content-Type: application/json' \
  -d '{"recalculate": false}'

curl -X POST http://127.0.0.1:8000/system-a/metrics \
  -H 'Content-Type: application/json' \
  -d '{"recalculate": true}'
```

If `recalculate` is omitted or `false`, the endpoint evaluates every complete prediction/trace pair currently available without model calls. At least two complete cases are required; partial coverage is returned in the `coverage` object. `true` regenerates all cases through `text-embedding-3-small` and the configured generation model, overwrites those artifacts, and then evaluates them. Regeneration runs four independent cases concurrently by default. Set `SYSTEM_A_MAX_WORKERS` in `.env` to a value from 1 through 16 to change the bounded concurrency. The CLI equivalent is `--workers`, for example `.venv/bin/python -m scripts.run_system_a --all --workers 4`. Regeneration makes paid external OpenAI requests. Interactive documentation is available at `http://127.0.0.1:8000/docs`.

Run only a selected set of case IDs in parallel without loading ground truth:

```bash
curl -X POST http://127.0.0.1:8000/system-a/run-selected \
  -H 'Content-Type: application/json' \
  -d '{"instance_ids": ["inst_001", "inst_004", "inst_008"]}'
```

IDs are deduplicated in request order and validated against `data/warehouses/index.json`. The response contains each structured prediction, total and component timing, and the saved prediction/trace paths. This endpoint makes paid external embedding and generation requests but never reads ground truth.

## Output schema

The persisted prediction contains `instance_id` and one to three ranked `Hypothesis` objects. Each hypothesis has a closed-set `mechanism_type`, a mechanism claim, an allowed-column cohort predicate, evidence records, confidence in `[0,1]`, and considered confounders. The trace records the exact query, chunk population, ranked retrieved chunks and scores, model/token metadata, total pipeline elapsed time, LLM-call elapsed time, and leakage/citation checks. Timing uses a monotonic clock and seconds.

## Assumptions and limitations

- Dense retrieval uses `text-embedding-3-small`; it therefore requires network access and adds embedding latency and cost.
- Event aggregates are deliberately broad and fixed rather than adaptively investigated; this is the principal Vanilla RAG limitation.
- One general query must cover all fault types. Relevant telemetry can be crowded out by PRD or taxonomy chunks.
- The model can narrate retrieved aggregates but cannot interrogate the warehouse, validate confounders interactively, or recover evidence omitted by retrieval.
- Observational co-movement is reported as association, not proof of causality.
- Low-severity faults can be indistinguishable from noise; metrics must come from the completed offline run and must never be inferred from design mockups.
