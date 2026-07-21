"""Per-instance warehouse session — read-only DuckDB, with the canonical event view.

The agent-visible warehouse deliberately has **no `canonical` column** (that would leak
the answer — see the exposure boundary). So this session resolves the cursed raw
`event_name`s to canonical concepts via the frozen retriever (Phase 1a) and exposes a
read-only view `ev` that adds three derived columns the analytics compiler needs:

  * `canonical` — the resolved logical event (or 'unknown');
  * `day`       — floor((event_ts - BASE_DATE) / 1 day), matching the simulator exactly;
  * `period`    — 'post' if day >= changepoint_day else 'pre' (baseline vs recent).

Safety: the warehouse file is ATTACHed READ_ONLY into an in-memory connection, so the
canonical mapping table and the view live in memory and the underlying data is never
mutated. All SQL runs through here; the compiler owns it (design decision D8).
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from .retrieval.query import canonical_map

# Must match simulator/generator.py BASE_DATE and the day/period convention in
# simulator/checks.py (day = floored elapsed days; period splits at changepoint_day).
BASE_DATE = "2026-06-01 00:00:00"
CHANGEPOINT_DAY = 14
WINDOW_DAYS = 28

# Columns the agent may reference in a cohort predicate (matches the task whitelist).
COHORT_COLS = ("os", "device_type", "device_age_months", "geo", "channel", "is_returning")


class Warehouse:
    def __init__(self, path: str | Path, changepoint_day: int = CHANGEPOINT_DAY):
        self.path = str(Path(path).resolve())
        self.changepoint_day = changepoint_day
        self.con = duckdb.connect(":memory:")
        self.con.execute(f"ATTACH '{self.path}' AS w (READ_ONLY)")

        names = [r[0] for r in self.con.execute(
            "SELECT DISTINCT event_name FROM w.events").fetchall()]
        self.canonical = canonical_map(names)  # raw -> canonical concept

        self.con.execute("CREATE TABLE _canon(raw VARCHAR, canonical VARCHAR)")
        self.con.executemany("INSERT INTO _canon VALUES (?, ?)",
                             list(self.canonical.items()))
        self.con.execute(f"""
            CREATE VIEW ev AS
            SELECT e.*,
                   COALESCE(m.canonical, 'unknown') AS canonical,
                   CAST(floor(date_diff('second', TIMESTAMP '{BASE_DATE}',
                                        e.event_ts) / 86400.0) AS INTEGER) AS day,
                   CASE WHEN floor(date_diff('second', TIMESTAMP '{BASE_DATE}',
                                             e.event_ts) / 86400.0) >= {changepoint_day}
                        THEN 'post' ELSE 'pre' END AS period
            FROM w.events e
            LEFT JOIN _canon m ON e.event_name = m.raw
        """)

    # -- read-only query helpers (the compiler builds the SQL) --------------------
    def query(self, sql: str) -> list[tuple]:
        return self.con.execute(sql).fetchall()

    def df(self, sql: str):
        return self.con.execute(sql).df()

    def columns(self, sql: str) -> list[str]:
        cur = self.con.execute(sql)
        return [c[0] for c in cur.description]

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "Warehouse":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @classmethod
    def from_task(cls, task_path: str | Path) -> "Warehouse":
        """Open the warehouse referenced by a task JSON (paths are relative to data/)."""
        task = json.loads(Path(task_path).read_text())
        data_root = Path(task_path).resolve().parents[1]  # data/tasks/x.json -> data/
        return cls(data_root / task["warehouse"],
                   changepoint_day=task.get("changepoint_day", CHANGEPOINT_DAY))


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "data/warehouses/warehouse_inst_001.duckdb"
    wh = Warehouse(path)
    print(f"distinct raw names: {len(wh.canonical)}  "
          f"unknown: {sum(v == 'unknown' for v in wh.canonical.values())}")
    print("period split:", wh.query(
        "SELECT period, count(*) FROM ev GROUP BY period ORDER BY period"))
    print("day range:", wh.query("SELECT min(day), max(day) FROM ev"))
    print("top canonicals:", wh.query(
        "SELECT canonical, count(*) c FROM ev GROUP BY canonical ORDER BY c DESC LIMIT 6"))
