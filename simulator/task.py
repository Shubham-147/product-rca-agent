"""The TASK — the question posed to the agent, and what it must return.

This is the AGENT-VISIBLE half of each test case. It is deliberately NEUTRAL and
IDENTICAL across every instance (so A/B/C are compared apples-to-apples and the
prompt never leaks whether a fault exists). It states the symptom framing an
analyst genuinely has (which funnel, which two periods) but never the cohort or
mechanism. Written to data/tasks/task_<id>.json alongside a human-readable TASK.md.
"""
from __future__ import annotations

from .schemas import InstanceConfig

FUNNEL_STR = ("app_open → home_view → product_browse → product_detail_view → "
              "add_to_cart → cart_view → checkout_start → payment_submit → order_confirmed")

WHITELIST_COLS = ["os", "device_type", "device_age_months", "geo", "channel", "is_returning"]


def question(cfg: InstanceConfig) -> str:
    end = cfg.window_days - 1
    cp = cfg.changepoint_day
    return f"""You are a product-analytics agent investigating the conversion funnel of a mobile
e-commerce app ("ShopFunnel").

DATA AVAILABLE TO YOU
- An event warehouse (DuckDB) with two tables: `events` and `users` (real user
  telemetry). You query it with SQL.
- A product spec (PRD) describing each screen's INTENDED behaviour.
- An event dictionary mapping raw event names to their meaning. The raw names are
  messy: the same logical event fires under several aliases with inconsistent
  casing, some names are deprecated, some are undocumented. You must resolve them.

THE FUNNEL
{FUNNEL_STR}

THE WINDOW
The data spans {cfg.window_days} days. A change may have been introduced at day {cp}.
Compare the BASELINE period (days 0–{cp - 1}) against the RECENT period (days {cp}–{end}).

YOUR TASK
Identify the root cause(s) of any conversion regression between the two periods.
For EACH root cause, return one hypothesis with:
  • mechanism_type — one of: dead_screen, checkout_latency, cold_start,
    crash_concentration, payment_failure, innocent_dropoff
  • mechanism — a specific, testable claim (name the MECHANISM, not the symptom)
  • affected_cohort — an explicit SQL WHERE predicate over user attributes
    ({", ".join(WHITELIST_COLS)}) identifying EXACTLY the affected users
  • evidence — the queries and numbers that support it
  • confidence — 0..1
  • confounders_considered — alternative explanations you checked and ruled out
    (e.g. old devices independently causing both crashes and churn)

Return a ranked list, most likely first. If there is NO actionable product fault
(the change is by design, a traffic-mix shift, or a pre-existing correlation, not
a defect), return a single hypothesis with mechanism_type "innocent_dropoff"
explaining why."""


def build_task(cfg: InstanceConfig) -> dict:
    return {
        "instance_id": cfg.instance_id,
        "question": question(cfg),
        "funnel": FUNNEL_STR,
        "window_days": cfg.window_days,
        "changepoint_day": cfg.changepoint_day,
        "cohort_whitelist_columns": WHITELIST_COLS,
        "warehouse": f"warehouses/warehouse_{cfg.instance_id}.duckdb",
        "corpus": {"prd": "corpus/spec/prd.md",
                   "taxonomy": "corpus/taxonomy/events.jsonl",
                   "tickets": "corpus/spec/tickets/"},
        "output_contract": "list[Hypothesis]  (see simulator/schemas.py)",
    }


TASK_MD = """# The Task (what every test case asks the agent)

Given a generated instance, the agent receives the agent-visible artifacts
(warehouse + PRD + event dictionary) and the question below, and must return a
ranked `list[Hypothesis]` (schema in `simulator/schemas.py`).

The question is **identical for every instance** — the agent is never told whether
a fault exists, which cohort, or which mechanism. It must discover all of that.

The correct answer for each instance is the held-out `ground_truth/gold_<id>.json`.
A test case = (task_<id>.json  +  warehouse_<id>.duckdb  +  corpus)  scored against
(gold_<id>.json). Run one with:

    python -m eval.run_case --id inst_003

---

"""
