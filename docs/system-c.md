# System C — LangGraph multi-agent + falsifier

## What changed

This document is the durable implementation log requested for System C.

| File | Change | Reason |
| :-- | :-- | :-- |
| `requirements.txt` | Added `langgraph>=0.2`. | System C uses a compiled cyclic state graph. |
| `agent/systems/system_c.py` | Added investigator and falsifier agents, typed graph state and verdict, bounded conditional cycle, shared tool registration, usage aggregation, trace generation, and the `SystemC` adapter. | Implements the architecture shown in the design while preserving the A/B evaluation contract. |
| `agent/systems/__init__.py` | Exported System C and its builders. | Makes the new system available through the systems package. |
| `eval/run_suite.py` | Added `C` to `--system` and constructs `SystemC`. | Keeps the same scored full-suite command used by A and B. |
| `scripts/run_system_c.py` | Added a one-instance run-and-score command with `--max-cycles`. | Provides a fast demo/debug entrypoint. |
| `README.md` | Added System C overview and commands. | Makes setup and execution discoverable. |

## Runtime graph

```text
START -> investigator -> falsifier -> accepted/max cycles? -> END
                           | no
                           +-------> investigator (with falsifier feedback)
```

The default is two investigation cycles. `recursion_limit` is also set from that
bound, so a graph-routing defect cannot create an unbounded paid loop.

## Agent responsibilities

- **Investigator:** locates the funnel regression, confirms the mechanism/SLO, finds
  the concentrated cohort, resolves it, and rules out a confounder.
- **Falsifier:** independently attacks the proposed mechanism, SLO evidence, cohort
  concentration, sample size, predicate validity, and confounders using fresh tool
  calls. Its typed verdict contains `accepted`, a summary, failed tests, and required
  follow-up.
- **Revision:** a rejected verdict is injected into the next investigator prompt. The
  investigator is instructed to run the missing comparison or replace its hypothesis,
  rather than defend the previous answer rhetorically.

Both agents can access only the existing typed, read-only tools: `funnel`,
`metric_by_segment`, `cohort_resolve`, `resolve_events`, and `retrieve_spec`. Neither
agent receives raw SQL or scorer-only ground truth.

## Configuration and commands

System C uses the same `RCA_` environment variables as System B:

```bash
RCA_LLM_BASE_URL=http://localhost:4000
RCA_LLM_API_KEY=...
RCA_MODEL_NAME=gpt-4o
```

Run one case:

```bash
python -m scripts.run_system_c --id inst_001 --max-cycles 2
```

Run the shared evaluation suite:

```bash
python -m eval.run_suite --system C --workers 1
```

Start with one worker because each case can make investigator and falsifier model
calls. Increase concurrency only within the configured proxy/provider rate limits.

## Output and failures

System C returns the same `RunResult` as A and B, including scorer-ready hypotheses,
requests, tool calls, tokens, latency, and a readable trace. Suite traces are written
to `eval/traces/system_C_<instance>.md`; suite results go to
`eval/results/suite_system_C.json`.

Node/model/budget failures become a typed `RunResult.error`, allowing the suite to
continue. A missing model configuration raises a direct setup error, matching System
B. If the last permitted cycle is rejected, System C emits the best revised candidate
and records the rejection in its trace rather than looping indefinitely.

## Verification checklist

```bash
python -m compileall agent/systems/system_c.py scripts/run_system_c.py eval/run_suite.py
python -m eval.run_suite --help
python -m scripts.run_system_c --help
```

A live end-to-end run additionally requires the configured LLM proxy and generated
benchmark data.

## Verification performed (2026-07-22)

- `git diff --check` passed.
- `.venv/bin/python -m compileall -q agent/systems/system_c.py scripts/run_system_c.py eval/run_suite.py` passed.
- `.venv/bin/python -m eval.run_suite --help` passed and displayed
  `--system {A,B,C}`.
- `.venv/bin/python -m scripts.run_system_c --help` passed.
- Both typed agents constructed successfully against the installed LangGraph/Pydantic
  AI environment.
- The one-case command reached the configured LLM but the external endpoint returned
  `ModelAPIError: Connection error`. The CLI converted it into the expected non-fatal
  error row. A successful hypothesis run remains dependent on that proxy being online.
