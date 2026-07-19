from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from .loaders import assert_allowed


COHORT_COLUMNS = ["os", "device_type", "geo", "channel", "is_returning", "device_age_months"]


def _rate(frame: pd.DataFrame, names: set[str]) -> float:
    if frame.empty:
        return 0.0
    return float(frame.groupby("user_id")["event_name"].apply(lambda x: x.isin(names).any()).mean())


def build_event_summary(warehouse: Path, data_root: Path, taxonomy_text: str, changepoint_day: int) -> str:
    """Load telemetry once and derive a deterministic evidence document in pandas."""
    warehouse = assert_allowed(warehouse, data_root)
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        events = con.execute("SELECT * FROM events").df()
        users = con.execute("SELECT * FROM users").df()
    finally:
        con.close()
    forbidden = {"persona", "canonical", "fault_type", "affected_user_ids"}
    leaked = forbidden & ({c.lower() for c in events.columns} | {c.lower() for c in users.columns})
    if leaked:
        raise ValueError(f"Forbidden warehouse columns detected: {sorted(leaked)}")
    if events.empty or users.empty:
        raise ValueError("Warehouse events/users tables must be non-empty")

    start = pd.Timestamp(events.event_ts.min()).normalize()
    cut = start + pd.Timedelta(days=int(changepoint_day))
    events["period"] = events.event_ts.map(lambda x: "recent" if x >= cut else "baseline")
    taxonomy_names: dict[str, set[str]] = {}
    import json
    for line in taxonomy_text.splitlines():
        row = json.loads(line)
        desc = row["description"].lower()
        for label, needle in {
            "home_view": "views the home screen", "product_detail_view": "product detail page",
            "checkout_start": "begins the checkout", "payment_submit": "submits a payment",
            "order_confirmed": "order successfully placed", "payment_error": "payment attempt failed",
            "cold_start": "cold start", "api_error": "api error", "crash": "unhandled crash",
        }.items():
            if needle in desc:
                taxonomy_names.setdefault(label, set()).add(row["event_name"])

    lines = [f"TELEMETRY SUMMARY instance={events.instance_id.iloc[0]} cut={cut.date()} rows={len(events)} users={len(users)}",
             "All figures below are deterministic aggregations of the allowed warehouse, not ground truth."]
    for logical, names in sorted(taxonomy_names.items()):
        vals = []
        for period in ("baseline", "recent"):
            vals.append(f"{period} user-rate={_rate(events[events.period == period], names):.4f}")
        lines.append(f"logical_event={logical}; aliases={sorted(names)}; " + "; ".join(vals))

    dims = ["os", "device_type", "geo", "channel", "is_returning"]
    for dim in dims:
        for value in sorted(users[dim].dropna().unique(), key=str):
            part = events[events[dim] == value]
            if len(part) < 100:
                continue
            stats = []
            for period in ("baseline", "recent"):
                f = part[part.period == period]
                checkout = f[f.screen == "checkout"].latency_ms.dropna()
                cold_names = taxonomy_names.get("cold_start", set())
                pay_names = taxonomy_names.get("payment_submit", set())
                order_names = taxonomy_names.get("order_confirmed", set())
                pay_users = set(f[f.event_name.isin(pay_names)].user_id)
                order_users = set(f[f.event_name.isin(order_names)].user_id)
                pay_success = len(pay_users & order_users) / len(pay_users) if pay_users else 0.0
                crash_rate = float(f.groupby("user_id").is_crash.max().mean()) if not f.empty else 0.0
                cold = f[f.event_name.isin(cold_names)].latency_ms.dropna()
                stats.append(f"{period}[users={f.user_id.nunique()}, checkout_p95={checkout.quantile(.95) if len(checkout) else 0:.0f}ms, cold_p95={cold.quantile(.95) if len(cold) else 0:.0f}ms, crash_user_rate={crash_rate:.4f}, payment_success={pay_success:.4f}]")
            lines.append(f"cohort {dim}={value!r}: " + " ".join(stats))
    for method in sorted(events.payment_method.dropna().unique(), key=str):
        part = events[events.payment_method == method]
        vals=[]
        for period in ("baseline", "recent"):
            f=part[part.period==period]; pay=set(f[f.event_name.isin(taxonomy_names.get('payment_submit',set()))].user_id); order=set(f[f.event_name.isin(taxonomy_names.get('order_confirmed',set()))].user_id)
            vals.append(f"{period} success={len(pay & order)/len(pay) if pay else 0:.4f} attempts={len(pay)}")
        lines.append(f"payment_method={method!r}: " + "; ".join(vals))
    return "\n".join(lines)
