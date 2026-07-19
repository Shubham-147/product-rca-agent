from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .pipeline import run_case


def run_cases_parallel(
    data_root: Path,
    instance_ids: list[str],
    output_root: Path,
    max_workers: int = 4,
) -> list[dict]:
    """Run independent System A cases concurrently with bounded fan-out."""
    if not 1 <= max_workers <= 16:
        raise ValueError("max_workers must be between 1 and 16")
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="system-a") as executor:
        futures = {
            executor.submit(run_case, data_root, iid, output_root): iid
            for iid in instance_ids
        }
        for future in as_completed(futures):
            iid = futures[future]
            results[iid] = future.result()
    return [results[iid] for iid in instance_ids]
