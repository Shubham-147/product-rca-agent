"""Post-generation checks: severity calibration readout + leakage guards.

These are the design-checks that catch tautology / leakage before an instance is
accepted (see docs/data-and-ui-plan.md §1.4, §1.6).
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from .faults import Fault, STEP_METRIC
from .generator import BASE_DATE
from .schemas import FaultType, InstanceConfig

FORBIDDEN_WAREHOUSE_COLS = {"persona", "canonical", "_persona", "_acq_day"}


def _prep(gen: dict, cfg: InstanceConfig) -> pd.DataFrame:
    """One row per session: user, day, reached-canonicals, crash flag, payment method."""
    ev = pd.DataFrame(gen["events"])
    ev["day"] = (pd.to_datetime(ev["event_ts"]) - pd.Timestamp(BASE_DATE)).dt.days
    g = ev.groupby("session_id")
    sess = pd.DataFrame({
        "user_id": g["user_id"].first(),
        "day": g["day"].min(),
        "canon": g["canonical"].apply(lambda s: set(s)),
        "has_crash": g["is_crash"].apply(lambda s: bool(np.any(s.values))),
        "pay_method": g["payment_method"].apply(
            lambda s: next((x for x in s if pd.notna(x)), None)),
    })
    sess["period"] = np.where(sess["day"] >= cfg.changepoint_day, "post", "pre")
    return sess


def _cond_rate(sub: pd.DataFrame, frm: str, to: str) -> float:
    reached = sub[sub["canon"].apply(lambda c: frm in c)]
    if len(reached) == 0:
        return float("nan")
    return float(reached["canon"].apply(lambda c: to in c).mean())


def measure_severity(gen: dict, cfg: InstanceConfig, fault: Fault) -> dict:
    """Realised severity = the local drop at the fault's affected step, pre vs post.

    Full-headroom metric (step conversion is 70-97% at baseline), so target pp is
    achievable and directly calibratable. Crash is reported as a crash-rate rise.
    """
    sess = _prep(gen, cfg)
    ft = fault.fault_type
    if ft == FaultType.NONE:
        pre = _cond_rate(sess[sess.period == "pre"], "app_open", "order_confirmed")
        post = _cond_rate(sess[sess.period == "post"], "app_open", "order_confirmed")
        pre, post = (0 if np.isnan(pre) else pre), (0 if np.isnan(post) else post)
        return {"realised_pp": 0.0, "aggregate_pp_shift": round(100 * (pre - post), 2)}

    users = pd.DataFrame(gen["users"]).set_index("user_id")

    def _attrs(uid):
        a = users.loc[uid]
        return {"os": a["os"], "device_type": a["device_type"],
                "device_age_months": a["device_age_months"]}

    if ft == FaultType.PAYMENT_FAILURE:
        coh = sess[sess["pay_method"] == fault.payment_method]
    else:
        coh = sess[sess["user_id"].map(lambda uid: fault.in_cohort(_attrs(uid)))]

    if ft == FaultType.CRASH_CONCENTRATION:
        pre = coh[coh.period == "pre"]["has_crash"].mean()
        post = coh[coh.period == "post"]["has_crash"].mean()
        pre, post = (0 if np.isnan(pre) else pre), (0 if np.isnan(post) else post)
        return {"realised_pp": round(100 * (post - pre), 2),
                "metric": "crash_rate_increase", "cohort_sessions": int(len(coh))}

    frm, to = STEP_METRIC[ft]
    pre = _cond_rate(coh[coh.period == "pre"], frm, to)
    post = _cond_rate(coh[coh.period == "post"], frm, to)
    realised = 0.0 if (np.isnan(pre) or np.isnan(post)) else round(100 * (pre - post), 2)
    return {"realised_pp": realised, "metric": f"P({to}|{frm})",
            "cohort_sessions": int(len(coh)),
            "pre": round(100 * (0 if np.isnan(pre) else pre), 1),
            "post": round(100 * (0 if np.isnan(post) else post), 1)}


def assert_no_leak(warehouse_path: Path) -> None:
    """Hard guard: the agent-visible warehouse must not contain answer columns."""
    con = duckdb.connect(str(warehouse_path), read_only=True)
    try:
        for tbl in ("events", "users"):
            # .description column names are reliable; PRAGMA table_info[0] is the cid, not the name
            cols = {d[0] for d in con.execute(f"SELECT * FROM {tbl} LIMIT 0").description}
            bad = cols & FORBIDDEN_WAREHOUSE_COLS
            if bad:
                raise AssertionError(f"LEAK: {tbl} exposes forbidden columns {bad}")
    finally:
        con.close()


def cohort_separability(gen: dict, affected: set[str]) -> dict:
    """Soft report: does any single visible column value near-perfectly flag affected users?

    High precision AND recall for one (col,value) would mean the answer is
    trivially readable from one column. Because cohorts are probabilistic subsets
    of overlapping personas, this should stay well below 1.0.
    """
    users = pd.DataFrame(gen["users"])
    users["affected"] = users["user_id"].isin(affected)
    n_aff = int(users["affected"].sum())
    worst = {"col": None, "value": None, "precision": 0.0, "recall": 0.0}
    if n_aff == 0:
        return {"n_affected": 0, "worst_single_col": worst}
    for col in ["os", "device_type", "device_age_months", "geo", "channel", "is_returning"]:
        for val, grp in users.groupby(col):
            prec = grp["affected"].mean()
            rec = int(grp["affected"].sum()) / n_aff
            if prec * rec > worst["precision"] * worst["recall"]:
                worst = {"col": str(col), "value": str(val),
                         "precision": round(float(prec), 3), "recall": round(float(rec), 3)}
    return {"n_affected": n_aff, "worst_single_col": worst}
