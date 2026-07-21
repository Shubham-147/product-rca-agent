"""The analytics compiler — the agent forms intent, this owns the SQL (decision D8).

RCA over a funnel is a *bounded* set of analytical ops, so a few parameterised
operations cover almost all of it. The agent never writes SQL on the default path; it
picks a metric, a segmentation, and a cohort predicate, and this module compiles and
runs the query against the read-only canonical view (`ev`) and the `users` table.

Three operations:
  * `funnel(segment_by?)`        — session-level step conversion, pre vs post, optionally
                                    sliced by a user attribute. The "symptom".
  * `metric_by_segment(...)`     — the workhorse: a named metric sliced by segment(s),
                                    pre vs post, with deltas. Mechanism confirmation and
                                    confounder analysis are both just this.
  * `cohort_resolve(cohort)`     — compile a Cohort DSL predicate to a user-id set + size.

Conversion convention matches simulator/checks.py exactly: per **session**, the set of
canonical steps reached; conversion(a->b) = P(reached b | reached a) over sessions.
Everything is read-only and segment columns are whitelisted (no injection surface).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .contracts import Cohort
from .warehouse import COHORT_COLS, Warehouse

# The canonical purchase funnel from the task (raw names already resolved in `ev`).
FUNNEL_STEPS = [
    "app_open", "home_view", "product_browse", "product_detail_view", "add_to_cart",
    "cart_view", "checkout_start", "payment_submit", "order_confirmed",
]

# Screens carrying a render-latency SLO (PRD §4). Used by the *_p95 latency metrics.
_LATENCY_SCREENS = ("app", "home", "browse", "product_detail", "cart", "checkout",
                    "payment", "confirmation")


@dataclass
class StepConversion:
    step_from: str
    step_to: str
    segment: dict[str, object]           # {} when unsegmented
    conv_pre: float | None               # % of sessions reaching `from` that reach `to`
    conv_post: float | None
    delta_pp: float | None               # post - pre, percentage points (negative = drop)
    denom_pre: int
    denom_post: int


@dataclass
class MetricRow:
    metric: str
    segment: dict[str, object]
    value_pre: float | None
    value_post: float | None
    delta: float | None
    n_pre: int
    n_post: int


@dataclass
class CohortResolution:
    predicate: str
    n_users: int
    user_ids: list[str] = field(default_factory=list)


def _check_segment_cols(cols: list[str]) -> None:
    bad = [c for c in cols if c not in COHORT_COLS]
    if bad:
        raise ValueError(f"segment_by columns not in whitelist {COHORT_COLS}: {bad}")


class Analytics:
    def __init__(self, wh: Warehouse):
        self.wh = wh

    # ---------------------------------------------------------------- funnel
    def funnel(self, segment_by: list[str] | None = None) -> list[StepConversion]:
        """Session-level step conversion pre vs post, optionally sliced by attributes."""
        segment_by = segment_by or []
        _check_segment_cols(segment_by)

        seg_select = "".join(f"any_value({c}) AS {c}, " for c in segment_by)
        flags = ", ".join(
            f"max(canonical = '{s}') AS f_{i}" for i, s in enumerate(FUNNEL_STEPS)
        )
        sess = self.wh.df(f"""
            SELECT session_id, period, {seg_select}{flags}
            FROM ev GROUP BY session_id, period
        """)

        rows: list[StepConversion] = []
        groups = sess.groupby(segment_by) if segment_by else [((), sess)]
        for key, sub in groups:
            seg = dict(zip(segment_by, key if isinstance(key, tuple) else (key,))) if segment_by else {}
            pre, post = sub[sub.period == "pre"], sub[sub.period == "post"]
            for i in range(len(FUNNEL_STEPS) - 1):
                a, b = f"f_{i}", f"f_{i+1}"
                rows.append(StepConversion(
                    step_from=FUNNEL_STEPS[i], step_to=FUNNEL_STEPS[i + 1], segment=seg,
                    conv_pre=_rate(pre, a, b), conv_post=_rate(post, a, b),
                    delta_pp=_delta(_rate(post, a, b), _rate(pre, a, b)),
                    denom_pre=int(pre[a].sum()), denom_post=int(post[a].sum()),
                ))
        return rows

    # -------------------------------------------------------- metric_by_segment
    def metric_by_segment(
        self, metric: str, segment_by: list[str] | None = None, where: str | None = None,
    ) -> list[MetricRow]:
        """A named metric sliced by segment(s), pre vs post, with deltas.

        metric ∈ {conversion:<from>-><to>, checkout_p95, screen_p95:<screen>,
                  cold_start_p95, crash_rate, payment_error_rate}."""
        segment_by = segment_by or []
        _check_segment_cols(segment_by)
        where_sql = f" AND ({where})" if where else ""
        grp = ", ".join(segment_by)
        grp_select = (grp + ", ") if grp else ""
        grp_by = ("GROUP BY period, " + grp) if grp else "GROUP BY period"

        if metric.startswith("conversion:"):
            a, b = metric.split(":", 1)[1].split("->")
            return self._conversion(a.strip(), b.strip(), segment_by, where)

        agg, filt = self._metric_expr(metric)
        df = self.wh.df(f"""
            SELECT period, {grp_select}{agg} AS value, count(*) AS n
            FROM ev WHERE {filt}{where_sql} {grp_by}
        """)
        return self._pivot_metric(metric, df, segment_by)

    def _conversion(self, a: str, b: str, segment_by, where) -> list[MetricRow]:
        where_sql = f" WHERE {where}" if where else ""
        seg_sel = "".join(f"any_value({c}) AS {c}, " for c in segment_by)
        sess = self.wh.df(f"""
            SELECT session_id, period, {seg_sel}
                   max(canonical='{a}') AS fa, max(canonical='{b}') AS fb
            FROM ev{where_sql} GROUP BY session_id, period
        """)
        out: list[MetricRow] = []
        groups = sess.groupby(segment_by) if segment_by else [((), sess)]
        for key, sub in groups:
            seg = dict(zip(segment_by, key if isinstance(key, tuple) else (key,))) if segment_by else {}
            pre, post = sub[sub.period == "pre"], sub[sub.period == "post"]
            out.append(MetricRow(
                metric=f"conversion:{a}->{b}", segment=seg,
                value_pre=_rate(pre, "fa", "fb"), value_post=_rate(post, "fa", "fb"),
                delta=_delta(_rate(post, "fa", "fb"), _rate(pre, "fa", "fb")),
                n_pre=int(pre["fa"].sum()), n_post=int(post["fa"].sum()),
            ))
        return out

    def _metric_expr(self, metric: str) -> tuple[str, str]:
        """Return (aggregate_sql, row_filter_sql) for a scalar metric."""
        if metric == "checkout_p95":
            return "quantile_cont(latency_ms, 0.95)", "screen='checkout' AND latency_ms IS NOT NULL"
        if metric == "cold_start_p95":
            return "quantile_cont(latency_ms, 0.95)", "canonical='app_cold_start' AND latency_ms IS NOT NULL"
        if metric.startswith("screen_p95:"):
            screen = metric.split(":", 1)[1]
            if screen not in _LATENCY_SCREENS:
                raise ValueError(f"unknown screen '{screen}', expected one of {_LATENCY_SCREENS}")
            return "quantile_cont(latency_ms, 0.95)", f"screen='{screen}' AND latency_ms IS NOT NULL"
        if metric == "crash_rate":
            return "100.0 * avg(CASE WHEN is_crash THEN 1 ELSE 0 END)", "1=1"
        if metric == "payment_error_rate":
            return "100.0 * avg(CASE WHEN canonical='payment_error' THEN 1 ELSE 0 END)", \
                   "canonical IN ('payment_submit','payment_error')"
        raise ValueError(
            f"unknown metric '{metric}'. Valid: conversion:<a>-><b>, checkout_p95, "
            "cold_start_p95, screen_p95:<screen>, crash_rate, payment_error_rate")

    def _pivot_metric(self, metric, df, segment_by) -> list[MetricRow]:
        out: list[MetricRow] = []
        keys = df[segment_by].drop_duplicates().itertuples(index=False) if segment_by else [()]
        for key in keys:
            seg = dict(zip(segment_by, key)) if segment_by else {}
            mask = pd.Series(True, index=df.index)
            for c, v in seg.items():
                mask &= df[c] == v
            sub = df[mask]
            pre = sub[sub.period == "pre"]
            post = sub[sub.period == "post"]
            vp = float(pre["value"].iloc[0]) if len(pre) else None
            vq = float(post["value"].iloc[0]) if len(post) else None
            out.append(MetricRow(
                metric=metric, segment=seg, value_pre=vp, value_post=vq,
                delta=(None if vp is None or vq is None else round(vq - vp, 2)),
                n_pre=int(pre["n"].iloc[0]) if len(pre) else 0,
                n_post=int(post["n"].iloc[0]) if len(post) else 0,
            ))
        return out

    # ------------------------------------------------------------ cohort_resolve
    def cohort_resolve(self, cohort: Cohort, with_ids: bool = False) -> CohortResolution:
        pred = cohort.to_sql()
        n = self.wh.query(f"SELECT count(DISTINCT user_id) FROM w.users WHERE {pred}")[0][0]
        ids: list[str] = []
        if with_ids:
            ids = [r[0] for r in self.wh.query(
                f"SELECT DISTINCT user_id FROM w.users WHERE {pred}")]
        return CohortResolution(predicate=pred, n_users=int(n), user_ids=ids)


def _rate(df, a: str, b: str) -> float | None:
    denom = int(df[a].sum())
    if denom == 0:
        return None
    return round(100.0 * float(df[(df[a]) & (df[b])].shape[0]) / denom, 1)


def _delta(post: float | None, pre: float | None) -> float | None:
    if post is None or pre is None:
        return None
    return round(post - pre, 1)


if __name__ == "__main__":
    wh = Warehouse("data/warehouses/warehouse_inst_001.duckdb")
    an = Analytics(wh)
    print("FUNNEL (overall):")
    for r in an.funnel():
        d = f"{r.delta_pp:+.1f}pp" if r.delta_pp is not None else "  n/a"
        print(f"  {r.step_from:20s} -> {r.step_to:20s} pre={r.conv_pre}  post={r.conv_post}  {d}")
    print("\ncheckout_p95 by os:")
    for r in an.metric_by_segment("checkout_p95", ["os"]):
        print(f"  os={r.segment['os']:12s} pre={r.value_pre}  post={r.value_post}  Δ={r.delta}")
