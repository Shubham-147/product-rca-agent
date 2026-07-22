# Comparison API

## Change record

- Removed `agent/system_a/api.py`; System A no longer owns an HTTP API.
- Removed `scripts/serve_system_a.py` and all references to its mutation endpoints.
- Added the root-level `api/` package.
- Added one read-only route: `GET /comparison`.
- Updated the root README and System A documentation.

## Run

```bash
.venv/bin/uvicorn api.app:app --host 127.0.0.1 --port 8000
```

The UI requests `http://127.0.0.1:8000/comparison`.

## Response

```json
{
  "aggregates": [
    {
      "system": "A",
      "model": "gpt-5.4-mini",
      "n": 24,
      "errors": 0,
      "top1_accuracy": 0.125,
      "top1_accuracy_faultcases": 0.143,
      "cohort_f1_mean_faultcases": 0.405,
      "decoy_fp_rate_nofault": 1.0,
      "total_tokens": 407836,
      "est_cost_usd": 0.3984,
      "mean_latency_s": 13.155
    }
  ],
  "cases": [
    {
      "instance_id": "inst_000",
      "gold_fault": "dead_screen",
      "has_fault": true,
      "systems": {
        "A": {"top_pred": "checkout_latency", "cohort_f1": 0.42},
        "B": {"top_pred": "dead_screen", "cohort_f1": 0.928},
        "C": {"top_pred": "innocent_dropoff", "cohort_f1": 0.0}
      }
    }
  ]
}
```

Every object under `cases[].systems.A`, `.B`, and `.C` contains the complete source
case record: `instance_id`, `gold_fault`, `has_fault`, `top_pred`, `top1_correct`,
`cohort_f1`, `false_positive`, `recall_at_3`, `top_cohort`, `tokens`, `input_tokens`,
`output_tokens`, `latency_s`, `n_tool_calls`, and `error`. The API aligns cases by
`instance_id` rather than relying on array order.

## Source and failure behavior

The endpoint reads these files on every request, so the UI sees the latest completed
suite without restarting the API:

- `eval/results/suite_system_A.json`
- `eval/results/suite_system_B.json`
- `eval/results/suite_system_C.json`

It returns `503` when a manifest is missing, `500` when JSON/schema structure is
invalid, and `409` when the systems do not contain the same cases. It never invokes a
model or modifies the manifests.

The default CORS allowlist includes both `localhost` and `127.0.0.1` on ports 3000 and
5173. Override it with the comma-separated `COMPARISON_UI_ORIGINS` environment variable.
