from __future__ import annotations

import json
from pathlib import Path


FORBIDDEN_PARTS = {"ground_truth", "gold", "persona"}


def assert_allowed(path: Path, allowed_root: Path) -> Path:
    path = path.resolve()
    root = allowed_root.resolve()
    if root not in path.parents and path != root:
        raise ValueError(f"Input is outside allowed root: {path}")
    if any(part.lower() in FORBIDDEN_PARTS or part.lower().startswith("gold_") for part in path.parts):
        raise ValueError(f"Ground-truth input rejected: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Required input file is missing: {path}")
    return path


def load_task(path: Path, data_root: Path) -> dict:
    obj = json.loads(assert_allowed(path, data_root).read_text())
    required = {"instance_id", "question", "changepoint_day", "cohort_whitelist_columns"}
    missing = required - obj.keys()
    if missing:
        raise ValueError(f"Malformed task; missing: {sorted(missing)}")
    return obj


def load_corpus(corpus_root: Path, data_root: Path) -> list[tuple[str, str]]:
    corpus_root = corpus_root.resolve()
    files = sorted(corpus_root.rglob("*.md")) + sorted(corpus_root.rglob("*.jsonl"))
    if not files:
        raise FileNotFoundError(f"No corpus documents under {corpus_root}")
    return [(str(assert_allowed(p, data_root).relative_to(data_root.resolve())), p.read_text()) for p in files]
