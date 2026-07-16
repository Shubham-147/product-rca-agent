"""Deterministic stub event-stream generator with planted faults."""

from __future__ import annotations

import csv
import json
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.generator.taxonomy import build_taxonomy, write_taxonomy

DEFAULT_SEED = 20260716
DEFAULT_USERS = 750

_FUNNEL = [
    ("app_open", "app_open", "lifecycle"),
    ("splash_view", "splash", "screen"),
    ("home_render", "home", "screen"),
    ("search_view", "search", "screen"),
    ("search_submit", "search", "interaction"),
    ("product_view", "product_detail", "screen"),
    ("add_to_cart", "product_detail", "commerce"),
    ("cart_view", "cart", "screen"),
    ("checkout_start", "checkout", "commerce"),
    ("shipping_view", "shipping", "screen"),
    ("shipping_submit", "shipping", "commerce"),
    ("payment_view", "payment", "screen"),
    ("payment_submit", "payment", "commerce"),
    ("order_complete", "confirmation", "commerce"),
    ("confirmation_view", "confirmation", "screen"),
    ("recommendations_view", "recommendations", "screen"),
    ("loyalty_view", "loyalty", "screen"),
]

_COLUMNS = [
    "user_id",
    "session_id",
    "timestamp",
    "event_name",
    "screen",
    "category",
    "device_tier",
    "os",
    "cold_start",
    "latency_ms",
    "payment_provider",
    "outcome",
]


def _variants() -> dict[str, list[str]]:
    variants: dict[str, list[str]] = defaultdict(list)
    for record in build_taxonomy():
        if not record["is_dead"]:
            canonical = record["is_alias_of"] or record["event_name"]
            variants[canonical].append(record["event_name"])
    return variants


def generate_stub_data(
    output_dir: Path, seed: int = DEFAULT_SEED, user_count: int = DEFAULT_USERS
) -> dict[str, Any]:
    """Generate taxonomy, event CSV, and a blinded ground-truth manifest."""
    if not 500 <= user_count <= 1000:
        raise ValueError("user_count must be between 500 and 1000 for the stub")

    output_dir.mkdir(parents=True, exist_ok=True)
    taxonomy_path = output_dir / "taxonomy.json"
    events_path = output_dir / "events.csv"
    manifest_path = output_dir / "manifest.json"
    write_taxonomy(taxonomy_path)

    rng = random.Random(seed)
    variants = _variants()
    rows: list[dict[str, Any]] = []
    hits: dict[str, list[str]] = defaultdict(list)
    start = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)

    def emit(
        user_id: str,
        session_id: str,
        when: datetime,
        canonical: str,
        screen: str,
        category: str,
        device_tier: str,
        os_name: str,
        cold: bool,
        provider: str,
        latency: int = 0,
        outcome: str = "ok",
    ) -> datetime:
        rows.append(
            {
                "user_id": user_id,
                "session_id": session_id,
                "timestamp": when.isoformat(),
                "event_name": rng.choice(variants[canonical]),
                "screen": screen,
                "category": category,
                "device_tier": device_tier,
                "os": os_name,
                "cold_start": str(cold).lower(),
                "latency_ms": latency,
                "payment_provider": provider,
                "outcome": outcome,
            }
        )
        return when + timedelta(milliseconds=rng.randint(250, 1800) + latency)

    for index in range(user_count):
        user_id = f"user_{index:04d}"
        session_id = f"session_{index:04d}"
        device_tier = rng.choices(["old", "mid", "new"], [0.22, 0.43, 0.35])[0]
        os_name = rng.choices(
            ["Android_10", "Android_14", "iOS_17"],
            [0.48, 0.27, 0.25] if device_tier == "old" else [0.12, 0.48, 0.40],
        )[0]
        cold = rng.random() < 0.24
        provider = rng.choices(["PayFast", "CardWorks", "WalletCo"], [0.28, 0.52, 0.20])[0]
        when = start + timedelta(seconds=index * 37)

        # Assignment probabilities create both causal faults and observational confounding.
        cold_suppression = cold and rng.random() < 0.30
        crash_fault = device_tier == "old" and os_name == "Android_10" and rng.random() < 0.32
        dead_screen = rng.random() < 0.045
        checkout_latency = rng.random() < 0.10
        payment_failure = provider == "PayFast" and rng.random() < 0.22

        for canonical, screen, category in _FUNNEL:
            if canonical == "home_render" and cold_suppression:
                hits["cold_start_home_suppression"].append(user_id)
                when = emit(user_id, session_id, when, "cold_start", "home", "performance", device_tier, os_name, cold, provider, outcome="home_suppressed")
                continue

            if canonical == "product_view" and crash_fault:
                hits["device_os_crash"].append(user_id)
                when = emit(user_id, session_id, when, "app_crash", screen, "error", device_tier, os_name, cold, provider, outcome="crash")
                break

            if canonical == "shipping_view" and dead_screen:
                hits["shipping_dead_screen"].append(user_id)
                when = emit(user_id, session_id, when, "api_error", screen, "error", device_tier, os_name, cold, provider, outcome="screen_not_rendered")
                break

            if canonical == "checkout_start" and checkout_latency:
                hits["checkout_latency"].append(user_id)
                latency = rng.randint(4500, 9000)
                when = emit(user_id, session_id, when, canonical, screen, category, device_tier, os_name, cold, provider, latency=latency, outcome="slow")
                when = emit(user_id, session_id, when, "checkout_slow", screen, "performance", device_tier, os_name, cold, provider, latency=latency, outcome="threshold_exceeded")
                if rng.random() < 0.42:
                    break
                continue

            if canonical == "payment_submit" and payment_failure:
                hits["payment_provider_failure"].append(user_id)
                when = emit(user_id, session_id, when, canonical, screen, category, device_tier, os_name, cold, provider, outcome="submitted")
                when = emit(user_id, session_id, when, "payment_failure", screen, "error", device_tier, os_name, cold, provider, outcome="provider_error")
                break

            # Promo is an optional decoy screen: skipping it is intended behavior.
            if canonical == "cart_view" and rng.random() < 0.18:
                when = emit(user_id, session_id, when, "promo_skip", "promo_interstitial", "interaction", device_tier, os_name, cold, provider, outcome="intentional_skip")

            when = emit(user_id, session_id, when, canonical, screen, category, device_tier, os_name, cold, provider)

        emit(user_id, session_id, when, "session_end", "session_end", "lifecycle", device_tier, os_name, cold, provider)

    with events_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "blinded": True,
        "seed": seed,
        "user_count": user_count,
        "faults": {
            "shipping_dead_screen": {
                "type": "dead_screen", "user_ids": hits["shipping_dead_screen"],
                "question": "Why are users disappearing when the shipping screen should render?",
                "mechanism_terms": ["shipping", "screen"], "expected_events": ["shipping_view", "api_error"],
                "severity_pp": 2,
            },
            "cold_start_home_suppression": {
                "type": "render_suppression", "user_ids": hits["cold_start_home_suppression"],
                "question": "Why does the home screen fail to render after a cold start?",
                "mechanism_terms": ["cold", "home", "render"], "expected_events": ["cold_start", "home_render"],
                "severity_pp": 4,
            },
            "device_os_crash": {
                "type": "cohort_crash", "user_ids": hits["device_os_crash"],
                "question": "Why are older Android users crashing before adding to cart?",
                "mechanism_terms": ["android", "crash"], "expected_events": ["app_crash"],
                "severity_pp": 8, "has_confounder": True,
            },
            "payment_provider_failure": {
                "type": "provider_failure", "user_ids": hits["payment_provider_failure"],
                "question": "Why did payment completion fall for one provider?",
                "mechanism_terms": ["payment", "provider"], "expected_events": ["payment_failure"],
                "severity_pp": 8,
            },
            "checkout_latency": {
                "type": "latency", "user_ids": hits["checkout_latency"],
                "question": "Why did checkout abandonment spike?",
                "mechanism_terms": ["checkout", "latency"], "expected_events": ["checkout_slow", "checkout_start"],
                "severity_pp": 16,
            },
        },
        "decoy": {
            "name": "promo_interstitial_skip",
            "explanation": "The optional promotion is designed to be skipped; skipping is not a fault.",
            "question": "Why are users skipping the optional promotion interstitial?",
            "expected_events": ["promo_skip"],
        },
        "confounder": {
            "name": "old_device",
            "explanation": "Old devices are more likely to run Android 10 and independently have higher churn/crash exposure.",
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"taxonomy_rows": len(build_taxonomy()), "event_rows": len(rows), "manifest": manifest}
