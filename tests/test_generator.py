"""Acceptance tests for the deterministic stub generator."""

import csv
import json

from src.generator.events import generate_stub_data


def test_stub_data_has_expected_shape_and_ground_truth(tmp_path) -> None:
    result = generate_stub_data(tmp_path, seed=12345, user_count=500)

    taxonomy = json.loads((tmp_path / "taxonomy.json").read_text())
    with (tmp_path / "events.csv").open(newline="", encoding="utf-8") as handle:
        events = list(csv.DictReader(handle))
    manifest = json.loads((tmp_path / "manifest.json").read_text())

    assert 50 <= len(taxonomy) <= 80
    assert len(events) > 500
    assert len({row["user_id"] for row in events}) == 500
    assert any(row["is_alias_of"] is not None for row in taxonomy)
    assert any(row["is_dead"] for row in taxonomy)
    dead_names = {row["event_name"] for row in taxonomy if row["is_dead"]}
    assert dead_names.isdisjoint({row["event_name"] for row in events})
    assert set(manifest["faults"]) == {
        "shipping_dead_screen",
        "checkout_latency",
        "cold_start_home_suppression",
        "device_os_crash",
        "payment_provider_failure",
    }
    assert all(fault["user_ids"] for fault in manifest["faults"].values())
    assert manifest["decoy"] and manifest["confounder"]
    assert result["event_rows"] == len(events)


def test_stub_generation_is_reproducible(tmp_path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    generate_stub_data(first, seed=77, user_count=500)
    generate_stub_data(second, seed=77, user_count=500)

    for filename in ("taxonomy.json", "events.csv", "manifest.json"):
        assert (first / filename).read_bytes() == (second / filename).read_bytes()

