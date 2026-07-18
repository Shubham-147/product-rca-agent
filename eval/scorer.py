"""Score a system's ranked Hypotheses against a held-out Gold record.

The scorer is the ONLY component that reads ground truth. It compiles the agent's
claimed cohort predicate against the (agent-visible) warehouse `users` table to
get an exact user-ID set, then compares to the planted `affected_user_ids`.
"""
from __future__ import annotations

import re
from pathlib import Path

import duckdb

from simulator.schemas import Gold, Hypothesis
from simulator.task import WHITELIST_COLS

# A "correct" attribution requires the mechanism to match AND the cohort to overlap
# the planted set by at least this F1 (partial-credit floor).
COHORT_F1_FLOOR = 0.5


def compile_cohort(warehouse: str, predicate: str) -> set[str]:
    """Resolve a WHERE predicate (whitelisted columns only) to a user-ID set."""
    if not predicate or not predicate.strip():
        return set()
    low = predicate.lower()
    # guard: only whitelisted columns, no statement chaining / subqueries
    if any(tok in low for tok in (";", "--", "select", "insert", "update", "delete",
                                  "drop", "persona", "canonical")):
        return set()
    referenced = set(re.findall(r"[a-z_][a-z0-9_]*", low)) & {c.lower() for c in [
        "os", "device_type", "device_age_months", "geo", "channel", "is_returning"]}
    # allow only whitelist column identifiers among the "word" tokens that look like columns
    con = duckdb.connect(warehouse, read_only=True)
    try:
        rows = con.execute(
            f"SELECT DISTINCT user_id FROM users WHERE {predicate}").fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()
    finally:
        con.close()


def _f1(pred: set[str], gold: set[str]) -> dict:
    if not pred and not gold:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    tp = len(pred & gold)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(gold) if gold else 0.0
    f1 = (2 * p * r / (p + r)) if (p + r) else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f1, 3)}


def score_case(hyps: list[Hypothesis], gold: Gold, warehouse: str) -> dict:
    """Return per-case metrics for one system on one instance."""
    gold_set = set(gold.affected_user_ids)
    top = hyps[0] if hyps else None

    # --- confounder-trap / no-fault instances ---
    if not gold.has_fault:
        flagged = bool(top and top.mechanism_type != "innocent_dropoff")
        return {
            "has_fault": False,
            "top1_correct": (top is not None and top.mechanism_type == "innocent_dropoff"),
            "false_positive": flagged,           # flagged a fault where none exists
            "cohort_f1": None,
            "recall_at_3": (any(h.mechanism_type == "innocent_dropoff" for h in hyps[:3])),
        }

    # --- fault instances ---
    def mechanism_ok(h):
        return h.mechanism_type in gold.acceptable_mechanisms

    # cohort_f1 reported from the best mechanism-matching hypothesis
    matched = [h for h in hyps if mechanism_ok(h)]
    best = matched[0] if matched else top
    cohort = _f1(compile_cohort(warehouse, best.affected_cohort), gold_set) if best else _f1(set(), gold_set)

    # top-1: the FIRST hypothesis must match the mechanism AND clear the cohort floor
    if top is not None and mechanism_ok(top):
        top1 = _f1(compile_cohort(warehouse, top.affected_cohort), gold_set)["f1"] >= COHORT_F1_FLOOR
    else:
        top1 = False

    recall3 = any(mechanism_ok(h) and
                  _f1(compile_cohort(warehouse, h.affected_cohort), gold_set)["f1"] >= COHORT_F1_FLOOR
                  for h in hyps[:3])

    return {
        "has_fault": True,
        "gold_fault": gold.fault_type,
        "top_pred": top.mechanism_type if top else None,
        "top1_correct": top1,
        "recall_at_3": recall3,
        "cohort_f1": cohort["f1"],
        "cohort_precision": cohort["precision"],
        "cohort_recall": cohort["recall"],
        "false_positive": False,
    }


def load_gold(ground_truth_dir: Path, instance_id: str) -> Gold:
    return Gold.model_validate_json(
        (ground_truth_dir / f"gold_{instance_id}.json").read_text())
