"""A deliberately NAIVE stand-in 'system' so the harness runs end-to-end today.

This is NOT the real agent — it is a placeholder that Shubham's agent (or systems
A/B/C) will replace. It only looks at two CLEAN columns (`is_crash`, `latency_ms`)
in the recent period and guesses. It cannot resolve cursed event names, so it is
blind to dead_screen / cold_start / payment_failure — which is exactly the kind of
naive baseline the project is meant to out-perform.

Interface (the contract every real system must also satisfy):
    run(warehouse_path: str, task: dict) -> list[Hypothesis]
"""
from __future__ import annotations

import duckdb

from simulator.schemas import Evidence, Hypothesis


def run(warehouse: str, task: dict) -> list[Hypothesis]:
    cp = task["changepoint_day"]
    con = duckdb.connect(warehouse, read_only=True)
    cut = f"TIMESTAMP '2026-06-01' + INTERVAL {cp} DAY"
    hyps: list[Hypothesis] = []

    # signal 1: crash rate by OS in the recent period
    crash = con.execute(f"""
        SELECT os, avg(CASE WHEN is_crash THEN 1.0 ELSE 0 END) AS rate, count(*) n
        FROM events WHERE event_ts >= {cut} GROUP BY os HAVING n > 200
        ORDER BY rate DESC""").fetchall()
    if crash and crash[0][1] > 0.01 and crash[0][1] > 2.5 * _median([r[1] for r in crash]):
        os_ = crash[0][0]
        hyps.append(Hypothesis(
            mechanism_type="crash_concentration",
            mechanism=f"Elevated crash rate concentrated on {os_} in the recent period.",
            affected_cohort=f"os = '{os_}'",
            evidence=[Evidence(claim=f"{os_} crash rate {crash[0][1]*100:.1f}% vs others",
                               sql="SELECT os, avg(is_crash::INT) FROM events GROUP BY os")],
            confidence=0.55,
            confounders_considered=["device age (not checked by this naive baseline)"]))

    # signal 2: checkout-screen p95 latency by OS in the recent period
    lat = con.execute(f"""
        SELECT os, quantile_cont(latency_ms, 0.95) p95, count(*) n
        FROM events WHERE screen='checkout' AND event_ts >= {cut}
        GROUP BY os HAVING n > 50 ORDER BY p95 DESC""").fetchall()
    if lat and lat[0][1] and lat[0][1] > 3000 and lat[0][1] > 1.6 * _median([r[1] for r in lat if r[1]]):
        os_ = lat[0][0]
        hyps.append(Hypothesis(
            mechanism_type="checkout_latency",
            mechanism=f"Checkout latency regression on {os_} (p95 {lat[0][1]:.0f}ms).",
            affected_cohort=f"os = '{os_}'",
            evidence=[Evidence(claim=f"{os_} checkout p95 {lat[0][1]:.0f}ms")],
            confidence=0.5,
            confounders_considered=[]))
    con.close()

    if not hyps:
        hyps.append(Hypothesis(
            mechanism_type="innocent_dropoff",
            mechanism="No strong crash/latency signal in the recent period.",
            affected_cohort="",
            evidence=[], confidence=0.4,
            confounders_considered=["traffic-mix shift", "device-age baseline"]))
    return hyps


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return 0
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2
