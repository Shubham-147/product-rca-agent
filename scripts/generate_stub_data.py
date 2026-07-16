#!/usr/bin/env python3
"""Regenerate Phase-1 stand-in data with a fixed seed."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.generator.events import DEFAULT_SEED, generate_stub_data  # noqa: E402


if __name__ == "__main__":
    result = generate_stub_data(PROJECT_ROOT / "data", seed=DEFAULT_SEED)
    print(
        f"Generated {result['taxonomy_rows']} taxonomy rows and "
        f"{result['event_rows']} events with seed {DEFAULT_SEED}."
    )

