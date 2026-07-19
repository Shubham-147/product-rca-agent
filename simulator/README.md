# `simulator/` — persona-driven benchmark generator

Generates the **benchmark** for the Product Discovery Copilot: per instance, a
pair of *(agent-visible warehouse + neutral task)* and *(held-out golden answer)*,
with a physically-enforced no-leakage boundary. See [../docs/data-and-ui-plan.md](../docs/data-and-ui-plan.md).

## Run
```bash
python -m venv .venv && source .venv/bin/activate      # or: uv venv .venv
pip install -r simulator/requirements.txt
python -m simulator.generate --n 24 --users 8000 --seed 1000 --out data
python -m simulator.inspect_instance --id inst_003     # agent's-eye "symptom" view
```

## Output layout
```
data/
  corpus/                         AGENT-VISIBLE (static, product-wide)
    spec/prd.md                   intended behaviour (never mentions faults)
    spec/tickets/*.md             synthetic support tickets (retrieval noise)
    taxonomy/events.jsonl         the cursed ~230-name data dictionary
  warehouses/                     AGENT-VISIBLE (per instance)
    warehouse_<id>.duckdb         events + users tables (NO persona, NO canonical)
    index.json                    instance list (ids only)
  ground_truth/                   SCORER-ONLY — never reachable from agent code
    gold_<id>.json                the held-out Gold record
    persona_<id>.json             user_id -> persona
    event_canonical_map.json      surface_name -> canonical (event-resolution gold)
    index.json                    full answers (fault, severity, describability)
```

## The exposure boundary (the load-bearing rule)
- The warehouse contains only what a real analytics stack has. `persona` and the
  true `canonical` event are **not** in it — the agent must rediscover cohorts
  (from `os`, `device_age_months`, …) and resolve cursed names (via the taxonomy).
- `checks.assert_no_leak()` fails the build if a forbidden column ever appears
  (verified: it catches an injected `persona`).

## What each fault plants (severity = additive drop at the affected step)
| Fault | Cohort (default) | Signature | Severity metric |
| :-- | :-- | :-- | :-- |
| dead_screen | `os='Android 12'` | api_error + drop at product_detail | P(product_detail\|browse) drop |
| checkout_latency | `os='iOS 17'` | high checkout latency + abandon | P(payment\|checkout) drop |
| cold_start | `os IN (Android 10,11)` | app_open with no home_view | P(home\|app_open) drop |
| crash_concentration | `os='Android 12' AND age>24` | crash spike | crash-rate increase |
| payment_failure | `payment_method='upi'` | payment_error, no order | P(order\|payment) drop |
| none (trap) | — | old-device crash+churn; post-changepoint traffic-mix shift | correct answer = "no fault" |

Confounders are **structural** (the `old_device_android` persona crashes and
churns at baseline). A confounder-trap instance plants no fault; the correct
answer is "no actionable fault — device-age / low-intent traffic is the driver."
Simpson instances pair an Android-cohort fault with a silent iOS improvement so
the aggregate looks flat.

## Known tuning items (calibration is iterative)
- Severities **4/8/16 pp** calibrate close to target across all faults; **2 pp**
  is at the sampling noise floor (can read slightly negative) — honest to record,
  it's what the detection-vs-severity curve is meant to expose. More users
  tightens it.
- `crash_concentration` severity is a crash-*rate* increase, not a step drop —
  it tracks target only roughly (expected; it's the "weakest, most interesting"
  metric per the brief).
- Taxonomy is ~230 surface forms; bump `n_variants` / `SYNONYMS` in `taxonomy.py`
  toward ~300 if desired.

## Module map
`product.py` funnel/screens · `personas.py` the 6 personas · `taxonomy.py` cursed
names + canonical map · `schemas.py` Pydantic contracts · `faults.py` fault library
+ cohorts · `generator.py` sim engine · `corpus.py` PRD/taxonomy writer ·
`writer.py` two-store output · `checks.py` leak guard + severity readout ·
`generate.py` CLI · `inspect_instance.py` symptom view.
