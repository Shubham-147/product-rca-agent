"""Acceptance tests for the embedded DuckDB event surface."""

from src.generator.events import generate_stub_data
from src.retrieval.db import load_events, run_sql


def test_count_and_group_by_queries(tmp_path, monkeypatch) -> None:
    generated = generate_stub_data(tmp_path / "data", seed=2468, user_count=500)
    db_path = tmp_path / "events.duckdb"
    monkeypatch.setenv("EVENTS_DB_PATH", str(db_path))

    loaded = load_events(tmp_path / "data" / "events.csv")
    count_result = run_sql("SELECT COUNT(*) AS event_count FROM events")
    grouped = run_sql(
        """
        SELECT device_tier, COUNT(*) AS event_count
        FROM events
        GROUP BY device_tier
        ORDER BY device_tier
        """
    )

    assert loaded == generated["event_rows"]
    assert int(count_result.loc[0, "event_count"]) == loaded
    assert set(grouped["device_tier"]) == {"mid", "new", "old"}
    assert (grouped["event_count"] > 0).all()

