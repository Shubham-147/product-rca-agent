# System A — Vanilla RAG: implementation, execution, and verification

This document is the operational record for System A only. No System B or System C code was added, and no test files or test cases were created or modified. Validation uses the actual System A application pipeline and runtime checks.

## 1. Repository assessment

The repository provides a generated product-RCA benchmark with 24 statistically independent cases. Each case contains an agent-visible task and DuckDB event warehouse. A shared corpus contains the PRD, event taxonomy, and support-ticket noise. Held-out gold records and persona/canonical maps are physically separated under `data/ground_truth/`.

The existing `eval/scorer.py` supplies cohort compilation and case scoring. The original `eval/run_case.py` loads gold before invoking a system, so System A does not use that harness for generation. Instead, generation and evaluation are separate commands, and evaluation refuses to start until every expected prediction has already been saved.

## 2. Files inspected

The implementation assessment inspected:

- `README.md`
- `requirements.txt`
- `data/README.md`
- `data/TASK.md`
- `data/tasks/task_inst_001.json`
- `data/corpus/spec/prd.md`
- `data/corpus/spec/tickets/ticket_0417.md`
- `data/corpus/spec/tickets/ticket_0455.md`
- `data/corpus/spec/tickets/ticket_0473.md`
- `data/corpus/taxonomy/events.jsonl`
- `data/warehouses/index.json`
- the `events` and `users` schemas and sample rows in `data/warehouses/warehouse_inst_001.duckdb`
- `data/ground_truth/gold_inst_001.json`, for evaluator-schema inspection only
- `data/ground_truth/index.json`, for evaluator-schema inspection only
- `simulator/schemas.py`
- `eval/baseline_agent.py`
- `eval/scorer.py`
- `eval/run_case.py`
- `docs/generated-data-overview.md`
- `docs/design/comparison-a-b-c.png`
- `docs/design/workbench-system-c.png`

The repository inventory also identified all 24 task files, all 24 warehouse files, and all files beneath `data/ground_truth/`. Existing test artifacts were not opened, run, created, or modified.

## 3. Input and ground-truth boundaries

System A generation may read only:

- `data/tasks/task_<instance>.json`
- `data/corpus/spec/prd.md`
- `data/corpus/spec/tickets/*.md`
- `data/corpus/taxonomy/events.jsonl`
- `data/warehouses/warehouse_<instance>.duckdb`
- `data/warehouses/index.json`

Evaluator-only files are:

- `data/ground_truth/gold_inst_*.json`
- `data/ground_truth/persona_inst_*.json`
- `data/ground_truth/event_canonical_map.json`
- `data/ground_truth/index.json`

Generation loader guards reject path components containing `ground_truth`, `gold`, or `persona`. Loaded warehouse columns are checked for `persona`, `canonical`, `fault_type`, and `affected_user_ids`. Ground truth is not loaded during ingestion, preprocessing, indexing, retrieval, prompting, generation, or artifact persistence.

The offline evaluator first verifies and loads every saved prediction. Only then does it access `data/ground_truth/`.

## 4. Architecture implemented

System A is a constrained Vanilla RAG pipeline:

1. Load the selected task and shared corpus with path validation.
2. Load the selected DuckDB `events` and `users` tables once.
3. Produce deterministic pandas aggregations for event rates, cohort latency, crash rate, and payment success.
4. Add those aggregates as a derived, agent-visible telemetry document.
5. Chunk allowed documents into stable content-derived chunk IDs.
6. Embed all chunks and the single query in one batched `text-embedding-3-small` request and rank chunks by cosine similarity.
7. Issue exactly one retrieval query and select the top 12 chunks.
8. Make exactly one structured OpenAI generation call.
9. Validate the returned `SystemAOutput` and nested `Hypothesis` records.
10. Reject citations to chunk IDs that were not retrieved.
11. Save the prediction and retrieval trace.
12. Run the separate offline evaluator only after all predictions exist.

The model has no tools. There is no agent loop, SQL generation by the model, query decomposition, multi-query retrieval, HyDE, reranking, LangGraph, falsification loop, or System B/C behavior.

## 5. Output schema

Each prediction contains:

```text
SystemAOutput
  instance_id: string
  hypotheses: 1..3 Hypothesis records

Hypothesis
  mechanism_type: closed mechanism enum
  mechanism: string
  affected_cohort: SQL predicate over allowed user attributes
  evidence: list of Evidence records
  confidence: number from 0 to 1
  confounders_considered: list of strings
```

Each trace records the instance, timestamp, single retrieval query, retrieval mode, top-k, total chunk count, ranked chunks and scores, model/token usage, total pipeline elapsed time, LLM-call elapsed time, and leakage/citation checks. Runs made before timing instrumentation retain explicit unavailable timing fields because their elapsed duration cannot be reconstructed.

## 6. Files created or modified

Created:

- `system_a/__init__.py`
- `system_a/schema.py`
- `system_a/loaders.py`
- `system_a/preprocess.py`
- `system_a/retrieval.py`
- `system_a/llm.py`
- `system_a/pipeline.py`
- `scripts/run_system_a.py`
- `scripts/evaluate_system_a.py`
- `docs/system-a.md`
- `SystemAReadme.md`

Modified:

- `requirements.txt` — added `openai`; scikit-learn was removed when retrieval changed from TF-IDF to `text-embedding-3-small`

Generated by the actual manual run:

- `artifacts/system_a/predictions/inst_001.json`
- `artifacts/system_a/traces/inst_001.json`

No file under `tests/` was created or modified.

## 7. Commands already executed and observed results

### Repository and data inventory

The repository and `data/` tree were enumerated, and relevant source files were read. The inventory found 24 tasks, 24 per-case warehouses, a shared corpus, 24 gold files, 24 persona files, a canonical event map, and a ground-truth index.

### Runtime dependency and warehouse inspection

The project virtual environment reported DuckDB 1.5.4, scikit-learn 1.9.0, OpenAI 1.109.1, and NumPy 2.5.1. `warehouse_inst_001.duckdb` contained:

- `events`: 252,634 rows
- `users`: 8,000 rows
- no forbidden persona or canonical columns

### Compilation check

Executed:

```bash
.venv/bin/python -m compileall -q system_a scripts/run_system_a.py scripts/evaluate_system_a.py
```

Observed result: successful completion with no syntax errors.

### Retrieval-only inspection

The real loader, deterministic preprocessor, chunker, index, and single-query retriever were executed for `inst_001`. Observed result:

```text
chunk_count: 32
retrieval_mode: single_query_tfidf
top_k: 12
```

Retrieved sources included PRD, taxonomy, and derived telemetry chunks. No ground-truth source was present.

### Runtime ground-truth rejection

The loader was invoked with `data/ground_truth/gold_inst_001.json`. Observed result:

```text
ValueError Ground-truth input rejected: .../data/ground_truth/gold_inst_001.json
```

### Runtime unsupported-ID handling

System A was invoked locally with `inst_999`. Observed result:

```text
FileNotFoundError Required input file is missing: .../data/tasks/task_inst_999.json
```

### Actual end-to-end manual case

The complete System A pipeline was executed for `inst_001` with the configured model. The persisted trace reports:

```text
instance_id: inst_001
model: gpt-5.4-mini
retrieval_mode: single_query_tfidf
chunk_count: 32
top_k: 12
prompt_tokens: 4850
completion_tokens: 1209
ground_truth_loaded: false
forbidden_columns: none
unsupported_citations: []
```

The structured top-ranked prediction was:

```json
{
  "mechanism_type": "checkout_latency",
  "affected_cohort": "(os = 'iOS 17' OR device_type = 'budget')",
  "confidence": 0.93
}
```

This is an actual persisted model result, not a fabricated or design-mockup result. It has not yet been scored because predictions for all cases do not yet exist.

## 8. Sample retrieval trace

The `inst_001` trace contains 12 retrieved chunks. Its first five ranked entries begin with:

```text
0.324022  chunk_5cb8de39a215  corpus/spec/prd.md
0.236977  chunk_27e068d08d62  corpus/spec/prd.md
0.213354  chunk_72b640a9b66c  corpus/spec/prd.md
0.205627  chunk_d58e8f9b4573  corpus/spec/prd.md
0.188866  chunk_c97a0af72121  corpus/spec/prd.md
```

The retrieved set also contains the derived telemetry chunks cited by the prediction. The full trace is `artifacts/system_a/traces/inst_001.json`.

## 9. Sample structured prediction

The actual prediction is saved at `artifacts/system_a/predictions/inst_001.json`. It ranks `checkout_latency` first and `crash_concentration` second. The first hypothesis cites the observed iOS 17 checkout p95 change from 1,294 ms to 4,778 ms and the PRD checkout p95 acceptance bar of less than 2,000 ms.

The wording treats latency as plausibly associated with conversion impact rather than claiming experimentally proven causality.

## 10. How to run one case

From the repository root:

```bash
cd /Users/home/capstone/product-rca-agent
source .venv/bin/activate
python -m scripts.run_system_a --id inst_001
```

System A automatically loads the repository-root `.env` without overriding variables already supplied by the shell. This sends the retrieved PRD/taxonomy context and derived telemetry to the configured OpenAI endpoint.

Inspect the saved artifacts:

```bash
python -m json.tool artifacts/system_a/predictions/inst_001.json
python -m json.tool artifacts/system_a/traces/inst_001.json
```

## 11. How to run every available case

```bash
source .venv/bin/activate
python -m scripts.run_system_a --all
```

Verify that all 24 predictions and traces exist:

```bash
find artifacts/system_a/predictions -name '*.json' | wc -l
find artifacts/system_a/traces -name '*.json' | wc -l
```

Both counts must be `24` before evaluation.

## 12. Offline evaluation

After all predictions exist:

```bash
python -m scripts.evaluate_system_a
python -m json.tool artifacts/system_a/metrics.json
```

The evaluator writes aggregate and per-case metrics to `artifacts/system_a/metrics.json`. It reports attribution top-1, recall@3, mean cohort F1, and no-fault false-positive rate.

Current status: the all-case run and aggregate evaluation have not been executed. Therefore there are no aggregate metrics to report yet.

## 13. Runtime verification commands

Validate every saved prediction against the application schema:

```bash
python - <<'PY'
from pathlib import Path
from system_a.schema import SystemAOutput

files = sorted(Path("artifacts/system_a/predictions").glob("*.json"))
for path in files:
    SystemAOutput.model_validate_json(path.read_text())
print(f"Validated {len(files)} structured predictions")
PY
```

Check traces for forbidden sources:

```bash
rg -n '"source":.*(ground_truth|gold_|persona)' artifacts/system_a/traces
```

No output is the expected result.

Inspect the recorded leakage checks:

```bash
python - <<'PY'
import json
from pathlib import Path

for path in sorted(Path("artifacts/system_a/traces").glob("*.json")):
    trace = json.loads(path.read_text())
    print(path.name, trace["leakage_checks"])
PY
```

## 14. Vanilla RAG failure modes

- A single general query must cover every possible fault mechanism and cohort.
- PRD chunks can outrank telemetry chunks, reducing evidence recall.
- Fixed deterministic aggregates may omit the interaction needed to identify an exact cohort.
- The one-call model can over-broaden a cohort. For example, the actual `inst_001` prediction joined `iOS 17` and `budget` devices in its first predicate.
- Correlated crash and latency changes may lead the model to return multiple plausible mechanisms without an investigation loop.
- There is no adaptive query, cohort drill-down, confounder falsification, or evidence recovery.
- Low-severity signals may be indistinguishable from ordinary variation.
- A syntactically valid cohort predicate can still be semantically imprecise; the offline cohort-F1 score measures that limitation.

## 15. Remaining limitations and blockers

- Only `inst_001` has a persisted prediction and trace at present.
- The remaining 23 cases require 23 external structured LLM calls.
- Aggregate metrics cannot be produced until all 24 predictions exist.
- OpenAI endpoint access and valid `OPENAI_API_KEY`/`OPENAI_MODEL` configuration are required; there is intentionally no mock fallback.
- External-call cost and latency depend on the configured model.
- Observational evidence supports association and diagnosis, not experimental proof of causality.
