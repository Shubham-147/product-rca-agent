"""CLI: generate a batch of benchmark instances.

  python -m simulator.generate --n 6 --users 4000 --out data

Writes, under --out:
  corpus/            static PRD + cursed taxonomy   (AGENT-VISIBLE)
  warehouses/        warehouse_<id>.duckdb per instance + public index.json (AGENT-VISIBLE)
  ground_truth/      gold_<id>.json, persona_<id>.json, event_canonical_map.json, index.json (SCORER-ONLY)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .corpus import write_corpus
from .checks import assert_no_leak, cohort_separability, measure_severity
from .faults import ACCEPTABLE_MECHANISMS, make_fault
from .generator import generate
from .schemas import FaultType, Gold, InstanceConfig
from .task import build_task, question, TASK_MD
from . import product

# (fault_type, severity_pp, is_trap, is_simpson) — cycled to fill the batch.
# NOTE: Simpson pairs an Android-cohort fault with the iOS silent-improvement, so
# the compensating segment differs from the fault cohort (else they cancel).
_TEMPLATE = [
    (FaultType.DEAD_SCREEN, 8, False, False),
    (FaultType.CHECKOUT_LATENCY, 8, False, False),
    (FaultType.COLD_START, 8, False, False),
    (FaultType.CRASH_CONCENTRATION, 8, False, False),
    (FaultType.PAYMENT_FAILURE, 8, False, False),
    (FaultType.NONE, 0, True, False),
    (FaultType.CRASH_CONCENTRATION, 16, False, True),   # Simpson (Android cohort)
    (FaultType.DEAD_SCREEN, 4, False, False),
    (FaultType.CHECKOUT_LATENCY, 16, False, False),
    (FaultType.PAYMENT_FAILURE, 4, False, False),
    (FaultType.NONE, 0, True, False),
    (FaultType.COLD_START, 2, False, False),
    (FaultType.CHECKOUT_LATENCY, 4, False, False),
    (FaultType.DEAD_SCREEN, 16, False, False),
    (FaultType.CRASH_CONCENTRATION, 2, False, False),
    (FaultType.PAYMENT_FAILURE, 16, False, False),
    (FaultType.COLD_START, 16, False, False),
    (FaultType.CHECKOUT_LATENCY, 2, False, False),
    (FaultType.DEAD_SCREEN, 2, False, False),
    (FaultType.NONE, 0, True, False),
]


def build_config(i: int, base_seed: int, n_users: int, window: int, changepoint: int) -> InstanceConfig:
    ft, sev, trap, simpson = _TEMPLATE[i % len(_TEMPLATE)]
    return InstanceConfig(
        instance_id=f"inst_{i:03d}", seed=base_seed + i, n_users=n_users,
        window_days=window, changepoint_day=changepoint,
        fault_type=ft, severity_pp=float(sev),
        is_confounder_trap=trap, is_simpson=simpson,
    )


def build_gold(cfg: InstanceConfig, gen: dict, realised: dict) -> Gold:
    fault = make_fault(cfg)
    has_fault = cfg.fault_type != FaultType.NONE
    if cfg.is_confounder_trap:
        confounder = "low_intent"
    elif cfg.is_simpson:
        confounder = "simpson"
    else:
        confounder = "none"
    return Gold(
        instance_id=cfg.instance_id, seed=cfg.seed, has_fault=has_fault,
        fault_type=cfg.fault_type.value,
        affected_user_ids=gen["affected_user_ids"] if has_fault else [],
        affected_cohort_predicate=fault.cohort_predicate if has_fault else "",
        severity_pp_target=cfg.severity_pp,
        severity_pp_realised=realised.get("realised_pp", 0.0),
        confounder_type=confounder,
        is_confounder_trap=cfg.is_confounder_trap,
        is_simpson=cfg.is_simpson,
        decoy_screens=product.DECOY_SCREENS,
        acceptable_mechanisms=ACCEPTABLE_MECHANISMS[cfg.fault_type],
        changepoint_day=cfg.changepoint_day,
        persona_mix=cfg.persona_mix or {},
        notes="Old-Device persona crashes+churns at baseline (standing device-age confounder).",
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--users", type=int, default=4000)
    ap.add_argument("--window", type=int, default=28)
    ap.add_argument("--changepoint", type=int, default=14)
    ap.add_argument("--out", type=str, default="data")
    args = ap.parse_args()

    out = Path(args.out)
    warehouses = out / "warehouses"
    ground_truth = out / "ground_truth"
    corpus = out / "corpus"
    tasks = out / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)

    print("== corpus ==")
    cstats = write_corpus(corpus, ground_truth)
    print(f"  taxonomy: {cstats['n_surface_forms']} surface forms, "
          f"{cstats['n_dictionary_entries']} documented, "
          f"{cstats['n_firing_names']} firing, "
          f"{cstats['n_undocumented_firing']} firing-but-undocumented, "
          f"{cstats['n_stale_documented']} stale-documented")

    public_index, gt_index = [], []
    print(f"\n== generating {args.n} instances ==")
    print("  (describ = how well ONE visible column describes the cohort; ~1 is fine "
          "for single-column cohorts — it's the discoverable answer, not a leak)")
    print(f"  {'id':10} {'fault':22} {'sev↑':5} {'sev↓':7} {'affected':9} {'describ':8}")
    for i in range(args.n):
        cfg = build_config(i, args.seed, args.users, args.window, args.changepoint)
        gen = generate(cfg, _forms())
        fault = make_fault(cfg)
        realised = measure_severity(gen, cfg, fault)
        gold = build_gold(cfg, gen, realised)
        from .writer import write_instance
        wh = write_instance(warehouses, ground_truth, gen, gold)
        assert_no_leak(wh)
        (tasks / f"task_{cfg.instance_id}.json").write_text(
            json.dumps(build_task(cfg), indent=2))
        sep = cohort_separability(gen, set(gold.affected_user_ids))
        w = sep["worst_single_col"]
        leak = round(w["precision"] * w["recall"], 3)
        print(f"  {cfg.instance_id:10} {cfg.fault_type.value:22} "
              f"{cfg.severity_pp:<5.0f} {realised.get('realised_pp', 0.0):<7} "
              f"{len(gold.affected_user_ids):<9} {leak:<8}")
        public_index.append({"instance_id": cfg.instance_id,
                             "warehouse": f"warehouses/warehouse_{cfg.instance_id}.duckdb",
                             "task": f"tasks/task_{cfg.instance_id}.json"})
        gt_index.append({"instance_id": cfg.instance_id, "fault_type": gold.fault_type,
                         "has_fault": gold.has_fault, "severity_pp_target": gold.severity_pp_target,
                         "severity_pp_realised": gold.severity_pp_realised,
                         "is_confounder_trap": gold.is_confounder_trap,
                         "is_simpson": gold.is_simpson, "n_affected": len(gold.affected_user_ids),
                         "worst_single_col_leak": leak})

    (warehouses / "index.json").write_text(json.dumps(public_index, indent=2))
    (ground_truth / "index.json").write_text(json.dumps(gt_index, indent=2))
    # human-readable task definition (one shared question across all instances)
    example_cfg = build_config(0, args.seed, args.users, args.window, args.changepoint)
    (out / "TASK.md").write_text(TASK_MD + "```\n" + question(example_cfg) + "\n```\n")
    print(f"\nwrote {args.n} instances to {out}/  (warehouses = agent-visible, "
          f"ground_truth = scorer-only)")


_FORMS_CACHE = None


def _forms():
    global _FORMS_CACHE
    if _FORMS_CACHE is None:
        from .taxonomy import build_taxonomy
        _FORMS_CACHE = build_taxonomy()
    return _FORMS_CACHE


if __name__ == "__main__":
    main()
