# Product RCA Agent — Standard Operating Procedure

This procedure covers the initial configuration, local setup, index creation,
command-line execution, API execution, verification, and safe shutdown of the
Product RCA Agent. Run all commands from the repository root.

## 1. Prerequisites

- Python 3.11 or newer
- Internet access during the first dependency/model installation
- An OpenAI API key with access to the model configured in `.env`
- Sufficient local disk space for generated DuckDB data, Chroma, and Hugging
  Face embedding/reranker model caches

The source benchmark warehouse is opened read-only. Runtime logs, cached
aggregates, and predicted cohorts are written to a separate runtime database.
Never point `RCA_RUNTIME_DUCKDB_PATH` at a source warehouse.

## 2. Create and activate the Python environment

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

## 3. Create the initial configuration

Copy the checked-in template. The resulting `.env` is intentionally ignored by
Git and must not be committed.

```bash
cp .env.example .env
```

Set at least these values in `.env`:

```dotenv
OPENAI_API_KEY=replace-with-your-provider-key
RCA_LLM_MODEL=gpt-5.4-mini

RCA_SOURCE_DUCKDB_PATH=data/events.duckdb
RCA_RUNTIME_DUCKDB_PATH=runtime/events.duckdb
RCA_CHROMA_PERSIST_PATH=runtime/chroma
```

`OPENAI_MODEL` is accepted as a compatibility alias for `RCA_LLM_MODEL`, but
use only one model variable to avoid ambiguity. Do not quote the API key and do
not place credentials in source code, request payloads, or shell history.

### Configuration reference

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | empty | Provider credential required for live A/B/C runs |
| `RCA_LLM_MODEL` | `gpt-5.4-mini` in `.env.example` | Structured-output LLM |
| `RCA_SOURCE_DUCKDB_PATH` | `data/events.duckdb` | Default read-only source database |
| `RCA_RUNTIME_DUCKDB_PATH` | `runtime/events.duckdb` | Writable logs, cache, and predicted cohorts |
| `RCA_CHROMA_PERSIST_PATH` | `runtime/chroma` | Persistent dense retrieval index |
| `RCA_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Dense embedding model |
| `RCA_RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder reranker |
| `RCA_BM25_CANDIDATE_COUNT` | `30` | Sparse candidates |
| `RCA_DENSE_CANDIDATE_COUNT` | `30` | Dense candidates |
| `RCA_RERANK_CANDIDATE_COUNT` | `20` | Fused candidates sent to reranking |
| `RCA_RETRIEVAL_TOP_K` | `8` | Final retrieved chunks |
| `RCA_RRF_CONSTANT` | `60` | Reciprocal Rank Fusion constant |
| `RCA_INDEX_BATCH_SIZE` | `64` | Dense indexing batch size |
| `RCA_MAX_CHUNKS_PER_PARENT` | `2` | Parent-diversity limit |
| `RCA_SQL_RESULT_ROW_LIMIT` | `200` | Maximum aggregate result rows |
| `RCA_MINIMUM_SEGMENT_SIZE` | `50` | Minimum cohort size |
| `RCA_SYSTEM_B_MAX_TOOL_CALLS` | `15` | System B total tool budget |
| `RCA_SYSTEM_B_MAX_RETRIEVAL_CALLS` | `4` | System B retrieval budget |
| `RCA_SYSTEM_B_MAX_ANALYTICAL_CALLS` | `10` | System B analytical budget |
| `RCA_SYSTEM_C_MAX_REVISIONS` | `2` | System C revision limit |
| `RCA_SYSTEM_C_MAX_NODE_EXECUTIONS` | `60` | System C graph limit sized for three candidates and two revisions each |
| `RCA_TOOL_TIMEOUT_SECONDS` | `30` | Per-tool timeout |
| `RCA_NODE_TIMEOUT_SECONDS` | `60` | Per-node timeout |
| `RCA_QUERY_TIMEOUT_SECONDS` | `30` | Query timeout |
| `RCA_MAX_HYPOTHESES` | `5` | Maximum report hypotheses |
| `RCA_MAX_PROMPT_CHUNKS` | `12` | Prompt retrieval-chunk ceiling |
| `RCA_MAX_CHUNK_CHARACTERS` | `6000` | Per-chunk prompt character ceiling |
| `RCA_LOG_LEVEL` | `INFO` | Application logging level |
| `RCA_API_CORS_ORIGINS` | localhost ports 3000 and 5173 | JSON list of allowed browser origins |

Keep the configured retrieval counts internally consistent:
`RCA_RETRIEVAL_TOP_K` must not exceed the rerank count, and the rerank count
must not exceed the combined dense and BM25 candidate counts.

## 4. Prepare benchmark data

If `data/tasks/task_inst_003.json` and its referenced warehouse already exist,
skip generation. Otherwise generate reproducible local data:

```bash
python -m simulator.generate --n 24 --users 8000 --seed 1000
```

Confirm the selected instance is agent-visible:

```bash
python -m simulator.inspect_instance --id inst_003
```

Each system resolves the actual source warehouse from
`data/tasks/task_<instance_id>.json`. Hidden files under `data/ground_truth/`
are scorer-only and must never be supplied to an agent, indexed, or referenced
in an analysis request.

## 5. Build the shared RAG index

Build or content-hash-update the index for the instance before its first run:

```bash
./scripts/build-rag-index --instance-id inst_003
```

The first execution may download the embedding and reranker weights. Only the
agent-visible taxonomy, PRD, tickets, funnel definitions, and metric definitions
are indexed; raw events and users are not embedded.

Expected successful output includes:

```text
RAG index ready at runtime/chroma for inst_003
```

## 6. Run a preflight check

Run credential-free tests and bytecode compilation before starting live runs:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src
```

Confirm that the runtime locations are writable and the chosen task exists:

```bash
test -f data/tasks/task_inst_003.json
test -d runtime/chroma
```

## 7. Execute from the command line

System A — fixed, non-agentic Vanilla RAG:

```bash
./scripts/run-system-a \
  --instance-id inst_003 \
  --symptom "Investigate the checkout funnel and identify the most likely root cause" \
  --funnel-name purchase \
  --suspected-screen checkout
```

System B — Pydantic AI agent with typed tools:

```bash
./scripts/run-system-b \
  --instance-id inst_003 \
  --symptom "Investigate the checkout funnel and identify the most likely root cause" \
  --funnel-name purchase \
  --suspected-screen checkout
```

System C — LangGraph workflow with validation and falsification:

```bash
./scripts/run-system-c \
  --instance-id inst_003 \
  --symptom "Investigate the checkout funnel and identify the most likely root cause" \
  --funnel-name purchase \
  --suspected-screen checkout
```

All three commands also accept optional ISO-8601 windows:

```bash
--incident-window 2026-01-15T00:00:00+00:00 2026-01-29T00:00:00+00:00
--baseline-window 2026-01-01T00:00:00+00:00 2026-01-15T00:00:00+00:00
```

The end of each window must be later than its start.

## 8. Start and use the FastAPI service

Start the API from the repository root:

```bash
source .venv/bin/activate
uvicorn src.api.app:app --host 127.0.0.1 --port 8000 --reload
```

Check health from a second terminal:

```bash
curl http://127.0.0.1:8000/api/v1/health
```

Interactive API documentation is available at
`http://127.0.0.1:8000/docs`.

Run all three systems sequentially:

```bash
curl -X POST 'http://127.0.0.1:8000/api/v1/analyse/compare' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
    "instance_id": "inst_003",
    "symptom": "Investigate the checkout funnel and identify the most likely root cause",
    "funnel_name": "purchase",
    "suspected_screen": "checkout"
  }'
```

To run one system, replace `/compare` with one of:

- `/api/v1/analyse/system-a`
- `/api/v1/analyse/system-b`
- `/api/v1/analyse/system-c`

The API request does not accept SQL, model names, paths, prompts, manifests, or
budget overrides. Executable code, script tags, shell commands, dynamic execution
calls, and instruction-override attempts are rejected in all user-controlled text
fields. Extra fields are rejected by schema validation.

## 9. Verify a completed run

A successful response has `status: "completed"` and an `RCAReport` containing:

- the requested `instance_id` and symptom;
- ranked hypotheses with explicit cohorts and limitations;
- query IDs for numerical evidence;
- source chunk IDs for product facts;
- run metadata with run ID, system name, timestamps, and completed status.

Immediately before retrieved product context is supplied to an LLM, the server
logs `pre_llm_retrieval_context` records containing each chunk ID, document type,
character count, and a preview capped at 300 characters. Sensitive-looking text
is redacted; raw telemetry and complete documents are never logged.

The logical provider request payload is also appended immediately before each
OpenAI call to `log/YYYY-MM-DD.txt`. Each line is a JSON record with timestamp,
system, stage, model, and payload. Provider credentials are never included. These
files may contain user symptoms, retrieved product context, and aggregate evidence;
they are Git-ignored and must be handled as local diagnostic data.

Runtime state is stored under `runtime/`. The source warehouse remains
read-only. Logs must not contain API keys, raw event tables, full user cohorts,
hidden manifest data, or private chain-of-thought.

## 10. Troubleshooting

- `DEPENDENCY_UNAVAILABLE`, authentication, or permission errors: verify
  `OPENAI_API_KEY`, model access, account limits, and `RCA_LLM_MODEL`.
- Hugging Face unauthenticated warning: optional `HF_TOKEN` configuration raises
  download limits; it is not required after models are cached locally.
- Chroma telemetry `capture()` errors: reinstall `requirements.txt`; the project
  pins `posthog<6` for Chroma compatibility.
- Missing task or warehouse: regenerate data and confirm
  `data/tasks/task_<instance_id>.json` references an existing warehouse.
- Missing/empty index: rerun `./scripts/build-rag-index --instance-id <id>`.
- Unresolved event: correct the product concept or taxonomy; do not bypass the
  event-resolution confidence guardrail.
- Tool or node budget exhausted: narrow the symptom. Do not disable safety
  budgets merely to force completion.
- Port 8000 already in use: stop the existing server or start with another port,
  then update the curl URL accordingly.
- Configuration changes are not reflected: restart the API because settings and
  pipeline dependencies are cached per process.

## 11. Shutdown and restart

Stop the foreground API with `Ctrl+C`. Wait for Uvicorn to report that shutdown
is complete before restarting. After changing `.env`, restart the process so
lazy cached settings are rebuilt.

Do not delete or overwrite the source warehouse during cleanup. The disposable
local runtime artifacts are `runtime/events.duckdb` and `runtime/chroma`, but
removing them discards run history, cached aggregates, materialized predicted
cohorts, and the retrieval index; rebuild the index before the next analysis.
