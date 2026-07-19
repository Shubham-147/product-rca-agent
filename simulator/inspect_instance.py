"""Quick look at a generated instance — the analyst's "symptom" view.

  python -m simulator.inspect_instance --id inst_003

Uses ONLY the agent-visible warehouse (no ground truth) — this is exactly what
the agent sees. Prints funnel conversion by step, pre vs post the changepoint,
and the noisiest signals. Seeds the UI's Funnel Overview later.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

from .faults import STEP_METRIC  # only for the canonical funnel order labels
from . import product

FUNNEL = [s.canonical for s in product.FUNNEL]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="inst_000")
    ap.add_argument("--out", default="data")
    ap.add_argument("--changepoint", type=int, default=14)
    args = ap.parse_args()

    wh = Path(args.out) / "warehouses" / f"warehouse_{args.id}.duckdb"
    con = duckdb.connect(str(wh), read_only=True)

    # NOTE: the agent must resolve these cursed names itself; we peek with a naive
    # substring match just to render a funnel here.
    print(f"== {args.id}: agent-visible summary ==")
    n_ev, n_u = con.execute("SELECT count(*), count(DISTINCT user_id) FROM events").fetchone()
    print(f"  {n_ev:,} events  |  {n_u:,} users  |  "
          f"{con.execute('SELECT count(DISTINCT event_name) FROM events').fetchone()[0]} distinct raw names")

    print("\n== funnel: distinct users reaching each step (naive name match) ==")
    match = {
        "app_open": "%open%|%session_start%|%launch%",
        "home_view": "%home%",
        "product_detail_view": "%pdp%|%product_page%|%item_detail%|%product_detail%",
        "add_to_cart": "%cart_add%|%add_to_cart%|%atc%|%add_item%",
        "checkout_start": "%checkout%|%chkout%|%begin_checkout%",
        "payment_submit": "%payment%|%pay%",
        "order_confirmed": "%order%|%purchase%|%txn_success%",
    }
    for canon, pat in match.items():
        likes = " OR ".join(f"lower(event_name) LIKE '{p}'" for p in pat.split("|"))
        for period, cond in (("all", "TRUE"),
                             ("pre", f"event_ts < TIMESTAMP '2026-06-01' + INTERVAL {args.changepoint} DAY"),
                             ("post", f"event_ts >= TIMESTAMP '2026-06-01' + INTERVAL {args.changepoint} DAY")):
            pass
        n = con.execute(f"SELECT count(DISTINCT user_id) FROM events WHERE {likes}").fetchone()[0]
        bar = "#" * int(40 * n / max(1, n_u))
        print(f"  {canon:22} {n:6}  {bar}")

    print("\n== crash rate & p95 checkout latency by os (a place a fault might hide) ==")
    rows = con.execute("""
        SELECT os,
               round(100.0*count(*) FILTER (WHERE is_crash)/count(*), 2) AS crash_pct,
               round(quantile_cont(latency_ms, 0.95) FILTER (WHERE screen='checkout'), 0) AS chk_p95
        FROM events GROUP BY os ORDER BY crash_pct DESC""").fetchall()
    print(f"  {'os':14} {'crash%':8} {'checkout_p95_ms':16}")
    for r in rows:
        print(f"  {str(r[0]):14} {str(r[1]):8} {str(r[2]):16}")
    con.close()


if __name__ == "__main__":
    main()
