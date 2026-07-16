"""DuckDB-backed SQL surface for the synthetic event stream.

The ``events`` table mirrors ``data/events.csv`` with this schema:

    user_id VARCHAR, session_id VARCHAR, timestamp TIMESTAMPTZ,
    event_name VARCHAR, screen VARCHAR, category VARCHAR,
    device_tier VARCHAR, os VARCHAR, cold_start BOOLEAN,
    latency_ms BIGINT, payment_provider VARCHAR, outcome VARCHAR
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV_PATH = PROJECT_ROOT / "data" / "events.csv"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "events.duckdb"


def _database_path() -> Path:
    """Return the configured DB path, allowing tests and callers to isolate storage."""
    return Path(os.getenv("EVENTS_DB_PATH", str(DEFAULT_DB_PATH)))


def load_events(
    csv_path: Path = DEFAULT_CSV_PATH, db_path: Path | None = None
) -> int:
    """Replace the ``events`` table from CSV and return the loaded row count."""
    csv_path = Path(csv_path)
    db_path = Path(db_path) if db_path is not None else _database_path()
    if not csv_path.is_file():
        raise FileNotFoundError(
            f"Event CSV not found at {csv_path}. Run scripts/generate_stub_data.py first."
        )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as connection:
        connection.execute(
            """
            CREATE OR REPLACE TABLE events AS
            SELECT
                CAST(user_id AS VARCHAR) AS user_id,
                CAST(session_id AS VARCHAR) AS session_id,
                CAST("timestamp" AS TIMESTAMPTZ) AS "timestamp",
                CAST(event_name AS VARCHAR) AS event_name,
                CAST(screen AS VARCHAR) AS screen,
                CAST(category AS VARCHAR) AS category,
                CAST(device_tier AS VARCHAR) AS device_tier,
                CAST(os AS VARCHAR) AS os,
                CAST(cold_start AS BOOLEAN) AS cold_start,
                CAST(latency_ms AS BIGINT) AS latency_ms,
                CAST(payment_provider AS VARCHAR) AS payment_provider,
                CAST(outcome AS VARCHAR) AS outcome
            FROM read_csv_auto(?, header = true)
            """,
            [str(csv_path)],
        )
        row_count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    return int(row_count)


def run_sql(query: str) -> pd.DataFrame:
    """Execute a read query against the event database and return a DataFrame.

    This intentionally stays small: it is the SQL tool surface that Phase 3 agents will
    call. Set ``EVENTS_DB_PATH`` to use a non-default database (useful in tests).
    """
    db_path = _database_path()
    if not db_path.is_file():
        raise FileNotFoundError(
            f"DuckDB file not found at {db_path}. "
            "Run `python -m src.retrieval.db` to build it."
        )
    with duckdb.connect(str(db_path), read_only=True) as connection:
        return connection.execute(query).fetchdf()


if __name__ == "__main__":
    count = load_events()
    print(f"Loaded {count} events into {DEFAULT_DB_PATH}")

