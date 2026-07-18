from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from src.analytics import DeterministicAnalytics
from src.config import AppSettings
from src.database import DuckDBManager
from src.guardrails import GuardrailError
from src.schemas import CohortDefinition


@pytest.fixture()
def database(tmp_path: Path) -> tuple[DuckDBManager, DeterministicAnalytics, Path]:
    source = tmp_path / "source.duckdb"
    runtime = tmp_path / "runtime" / "runtime.duckdb"
    connection = duckdb.connect(str(source))
    connection.execute("""
        CREATE TABLE users (
            user_id VARCHAR, os VARCHAR, device_type VARCHAR, device_age_months VARCHAR,
            geo VARCHAR, channel VARCHAR, is_returning VARCHAR, acquired_ts VARCHAR,
            instance_id VARCHAR
        )
    """)
    connection.execute("""
        CREATE TABLE events (
            user_id VARCHAR, session_id VARCHAR, event_ts VARCHAR, event_name VARCHAR,
            screen VARCHAR, os VARCHAR, device_type VARCHAR, device_age_months VARCHAR,
            geo VARCHAR, channel VARCHAR, is_returning VARCHAR, latency_ms VARCHAR,
            is_crash VARCHAR, payment_method VARCHAR, instance_id VARCHAR
        )
    """)
    connection.execute("CREATE TABLE ground_truth_manifest(secret VARCHAR)")
    users = [
        ("u1", " Android ", "Phone", "30", "IN", "organic", "true", "2026-01-01", "inst_1"),
        ("u2", "Android", "Phone", "10", "IN", "organic", "false", "2026-01-01", "inst_1"),
        ("u3", "Android", "Phone", "50", "IN", "paid", "false", "2026-01-01", "inst_1"),
        ("u4", "Android", "Phone", None, "IN", "paid", "true", "2026-01-01", "inst_1"),
        ("u5", "iOS", "Phone", "20", "US", "organic", "true", "2026-01-01", "inst_1"),
        ("x1", "Android", "Phone", "20", "IN", "organic", "true", "2026-01-01", "inst_2"),
    ]
    connection.executemany("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", users)
    base = datetime(2026, 7, 1, 12, 0)
    events: list[tuple] = []

    def add(uid: str, session: str, offset: int, name: str, *, latency=None, crash=False, iid="inst_1"):
        events.append((
            uid, session, str(base + timedelta(seconds=offset)), name, " Checkout ",
            "ANDROID" if uid != "u5" else "IOS", "phone", "30", "in", "organic",
            "true", None if latency is None else str(latency), str(crash).lower(), "card", iid,
        ))

    add("u1", "s1", 1, "checkout_start", latency=100)
    add("u1", "s1", 2, "crash", crash=True, latency=500)
    add("u1", "s1", 3, "order_confirmed", latency=1000)
    add("u2", "s2", 1, "checkout_start", latency=2000)
    add("u2", "s2", 2, "order_confirmed", latency=5000)
    add("u2", "s2", 3, "crash", crash=True)
    add("u3", "s3", 1, "checkout_start")
    add("u3", "s4", 2, "order_confirmed")
    add("u4", "s5", 1, "order_confirmed")
    add("u4", "s5", 2, "checkout_start")
    add("u5", "s6", 1, "screen_load", latency="bad")
    add("x1", "x", 1, "checkout_start", iid="inst_2")
    add("x1", "x", 2, "order_confirmed", iid="inst_2")
    events.append((None, "bad", str(base), "crash", None, None, None, None, None, None, None, None, None, None, "inst_1"))
    connection.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", events)
    connection.close()

    settings = AppSettings(
        source_duckdb_path=source,
        runtime_duckdb_path=runtime,
        chroma_persist_path=tmp_path / "chroma",
        minimum_segment_size=1,
    )
    manager = DuckDBManager(settings)
    return manager, DeterministicAnalytics(manager), source


def test_instance_isolation_and_normalized_summary(database) -> None:
    _, analytics, _ = database
    one = analytics.get_instance_summary("inst_1").rows[0]
    two = analytics.get_instance_summary("inst_2").rows[0]
    assert one["users"] == 5
    assert one["events"] == 11
    assert two["users"] == 1
    assert two["events"] == 2


def test_ordered_funnel_excludes_out_of_order_and_obeys_session(database) -> None:
    _, analytics, _ = database
    naive = analytics.get_naive_funnel("inst_1", ["checkout_start", "order_confirmed"])
    same = analytics.get_ordered_funnel("inst_1", ["checkout_start", "order_confirmed"])
    cross = analytics.get_ordered_funnel(
        "inst_1", ["checkout_start", "order_confirmed"], same_session=False
    )
    assert naive.rows[1]["users"] == 4
    assert same.rows[1]["users"] == 2
    assert cross.rows[1]["users"] == 3


def test_crash_denominator_and_checkout_crash_window(database) -> None:
    _, analytics, _ = database
    crash = analytics.compare_metric_by_dimension(
        "inst_1", "crash_rate", "os", minimum_users=1
    )
    android = next(row for row in crash.rows if row["dimension_value"] == "android")
    assert android["exposed_users"] == 4
    assert android["metric_value"] == pytest.approx(0.5)

    checkout = analytics.compare_metric_by_dimension(
        "inst_1", "checkout_crash_rate", "os", minimum_users=1
    )
    android_checkout = next(row for row in checkout.rows if row["dimension_value"] == "android")
    assert android_checkout["exposed_users"] == 4
    assert android_checkout["numerator_users"] == 1
    assert android_checkout["metric_value"] == pytest.approx(0.25)


def test_latency_percentile_and_bands(database) -> None:
    _, analytics, _ = database
    result = analytics.compare_metric_by_dimension(
        "inst_1", "latency_p50", "screen", minimum_users=1
    )
    row = result.rows[0]
    assert row["metric_value"] == pytest.approx(1000.0)
    assert row["latency_below_500"] == 1
    assert row["latency_500_999"] == 1
    assert row["latency_1000_1999"] == 1
    assert row["latency_2000_3999"] == 1
    assert row["latency_4000_plus"] == 1


def test_materialized_cohort_is_written_only_to_runtime(database) -> None:
    manager, analytics, source = database
    result = analytics.materialize_cohort(
        "run_1", "system_a", "hyp_1",
        CohortDefinition(instance_id="inst_1", os="android", description="Android users"),
    )
    assert result.rows == [{"materialized_users": 4}]
    with manager.runtime_connection() as runtime:
        assert runtime.execute("SELECT count(*) FROM predicted_cohorts").fetchone()[0] == 4
    source_connection = duckdb.connect(str(source), read_only=True)
    assert "predicted_cohorts" not in {
        row[0] for row in source_connection.execute("SHOW TABLES").fetchall()
    }
    source_connection.close()


def test_empty_materialized_cohort_is_valid(database) -> None:
    manager, analytics, _ = database
    result = analytics.materialize_cohort(
        "run_empty",
        "system_a",
        "hyp_empty",
        CohortDefinition(
            instance_id="inst_1",
            os="windows",
            description="No matching users",
        ),
    )

    assert result.rows == [{"materialized_users": 0}]
    with manager.runtime_connection() as runtime:
        persisted = runtime.execute(
            "SELECT count(*) FROM predicted_cohorts WHERE run_id = ?",
            ["run_empty"],
        ).fetchone()[0]
    assert persisted == 0


def test_source_is_read_only_and_manifest_is_not_exposed(database) -> None:
    manager, _, source = database
    with pytest.raises(GuardrailError):
        manager.execute_source_write_forbidden("UPDATE users SET os = 'x'")
    with pytest.raises(GuardrailError):
        manager.execute_source(
            "inst_1", "SELECT * FROM ground_truth_manifest", [], summary="forbidden"
        )
    assert "ground_truth_manifest" not in manager.list_exposed_source_relations()
    connection = duckdb.connect(str(source), read_only=True)
    assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 6
    connection.close()


def test_sequence_analysis_and_query_envelope(database) -> None:
    _, analytics, _ = database
    result = analytics.analyse_event_sequence(
        "inst_1", "checkout_start", ["crash"], "order_confirmed"
    )
    assert [row["users"] for row in result.rows] == [4, 2, 1]
    assert result.query_id.startswith("qry_")
    assert result.executed_sql
    assert result.parameters
    assert result.duration_ms >= 0
    assert result.row_count == 3
    assert result.result_summary


def test_debug_samples_are_hard_limited(database) -> None:
    _, analytics, _ = database
    result = analytics.get_debug_sample("inst_1", user_limit=2, event_limit=3)
    assert result.row_count <= 3
    assert len({row["user_id"] for row in result.rows}) <= 2
    with pytest.raises(GuardrailError):
        analytics.get_debug_sample("inst_1", user_limit=21)
    with pytest.raises(GuardrailError):
        analytics.get_debug_sample("inst_1", event_limit=51)
