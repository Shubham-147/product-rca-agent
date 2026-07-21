"""Offline retrieval eval — score the event resolver against the hidden canonical map.

This harness is the whole reason we build retrieval first: it measures resolution in
isolation (no agent, no LLM), so a failing agent later is never ambiguous between "bad
reasoning" and "bad retrieval". It is the ONLY retrieval component allowed to read
`data/ground_truth/event_canonical_map.json`.

What it does:
  1. Aligns the resolver's corpus-derived concept ids to gold canonicals (majority vote
     over each concept's firing aliases) — so cosmetic label diffs like
     `page_load`~`screen_load` don't count as errors, and any vocabulary
     over-merge/over-split shows up as an explicit alignment collision.
  2. Resolves every firing name leave-one-out and scores it:
       - micro P/R/F1 with abstention (precision over committed, recall over all),
       - macro-F1 over concepts (small concepts weigh equally),
       - slices: seen-in-taxonomy vs unseen (the true generalization set).
  3. Ablation table over signal subsets (charngram / fuzzy / hybrid / +dense) at
     forced top-1 (coverage=100%, no threshold) to isolate ranking power.
  4. For the best variant: per-concept table, top confusions, and a
     precision/coverage curve over abstention thresholds.

Gate: full-hybrid micro-F1 >= 0.85.

Usage:  ../.venv/bin/python -m eval.run_retrieval [--dense]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from agent.retrieval.concepts import build_concepts
from agent.retrieval.lexical import AnchorIndex, CharNgramSignal, FuzzySignal
from agent.retrieval.resolver import UNKNOWN, Resolver

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLD_PATH = REPO_ROOT / "data" / "ground_truth" / "event_canonical_map.json"
TAXONOMY_PATH = REPO_ROOT / "data" / "corpus" / "taxonomy" / "events.jsonl"


# --------------------------------------------------------------------------- data
def load_gold() -> dict[str, str]:
    return json.loads(GOLD_PATH.read_text())


def taxonomy_names() -> set[str]:
    return {
        json.loads(l)["event_name"]
        for l in TAXONOMY_PATH.read_text().splitlines()
        if l.strip()
    }


def align_concepts_to_gold(concepts, gold: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Map each resolver concept_id -> gold canonical by majority vote over its firing
    aliases. Returns (alignment, collisions) where collisions are gold canonicals that
    two concept_ids both claim (a vocabulary over-split — reported, not hidden)."""
    alignment: dict[str, str] = {}
    for c in concepts:
        votes = Counter(gold[a] for a in c.aliases if a in gold)
        if votes:
            alignment[c.concept_id] = votes.most_common(1)[0][0]
    claimed = Counter(alignment.values())
    collisions = sorted(g for g, n in claimed.items() if n > 1)
    return alignment, collisions


# ---------------------------------------------------------------------- scoring
def score(resolver: Resolver, gold: dict[str, str], alignment: dict[str, str], seen: set[str]):
    """Resolve every firing name leave-one-out; return per-name records."""
    records = []
    for name, gold_canon in gold.items():
        res = resolver.resolve(name, leave_one_out=True)
        pred_canon = alignment.get(res.concept_id, UNKNOWN) if res.resolved else UNKNOWN
        records.append(
            {
                "name": name,
                "gold": gold_canon,
                "pred": pred_canon,
                "raw_concept": res.concept_id,
                "confidence": res.confidence,
                "correct": res.resolved and pred_canon == gold_canon,
                "committed": res.resolved,
                "slice": "seen" if name in seen else "unseen",
            }
        )
    return records


def micro_prf(records) -> dict[str, float]:
    total = len(records)
    committed = sum(r["committed"] for r in records)
    correct = sum(r["correct"] for r in records)
    precision = correct / committed if committed else 0.0
    recall = correct / total if total else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"P": precision, "R": recall, "F1": f1, "coverage": committed / total, "n": total}


def macro_f1(records) -> float:
    labels = {r["gold"] for r in records}
    f1s = []
    for g in labels:
        tp = sum(r["correct"] and r["gold"] == g for r in records)
        fp = sum(r["committed"] and r["pred"] == g and r["gold"] != g for r in records)
        fn = sum(r["gold"] == g and not (r["correct"]) for r in records)
        p = tp / (tp + fp) if (tp + fp) else 0.0
        rc = tp / (tp + fn) if (tp + fn) else 0.0
        f1s.append(2 * p * rc / (p + rc) if (p + rc) else 0.0)
    return sum(f1s) / len(f1s) if f1s else 0.0


# --------------------------------------------------------------------- variants
def build_resolver(index, signal_names, min_raw, dense_signal=None, weights=None,
                   _cache={}):
    signals = []
    for n in signal_names:
        if n in ("charngram", "fuzzy"):
            # reuse fitted signals across variants/thresholds (TF-IDF fit is not free)
            if n not in _cache:
                _cache[n] = CharNgramSignal(index) if n == "charngram" else FuzzySignal(index)
            signals.append(_cache[n])
        elif n == "dense":
            signals.append(dense_signal)
    return Resolver(signals, weights=weights, min_raw=min_raw, min_margin=0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dense", action="store_true", help="include the bge-small dense signal")
    args = ap.parse_args()

    gold = load_gold()
    seen = taxonomy_names()
    concepts = build_concepts()
    index = AnchorIndex(concepts)
    alignment, collisions = align_concepts_to_gold(concepts, gold)

    n_seen = sum(1 for n in gold if n in seen)
    print(f"gold firing names: {len(gold)}  (seen-in-taxonomy {n_seen}, unseen {len(gold)-n_seen})")
    print(f"concepts: {len(concepts)}  aligned: {len(alignment)}  "
          f"gold canonicals covered: {len(set(alignment.values()))}/{len(set(gold.values()))}")
    if collisions:
        print(f"  !! alignment collisions (over-split concepts): {collisions}")
    print()

    dense_signal = None
    # (label, signal_names, weights) — weights let a reliable signal outvote weaker ones.
    variants = [
        ("charngram", ["charngram"], None),
        ("fuzzy", ["fuzzy"], None),
        ("charngram+fuzzy", ["charngram", "fuzzy"], None),
    ]
    if args.dense:
        from agent.retrieval.dense import DenseSignal
        dense_signal = DenseSignal(index)
        variants += [
            ("dense", ["dense"], None),
            ("cng+fz+dn (equal)", ["charngram", "fuzzy", "dense"], None),
            ("cng+fz+dn (fuzzy 2x)", ["charngram", "fuzzy", "dense"],
             {"fuzzy": 2.0, "charngram": 1.0, "dense": 1.0}),
            ("cng+fz+dn (fz3 cng2 dn1)", ["charngram", "fuzzy", "dense"],
             {"fuzzy": 3.0, "charngram": 2.0, "dense": 1.0}),
        ]

    # ---- ablation table (forced top-1, coverage = 100%) ----
    print("ABLATION  (leave-one-out, forced top-1 — pure ranking power)")
    print(f"  {'signals':28s} {'micro-F1':>9s} {'macro-F1':>9s} {'seen':>7s} {'unseen':>7s}")
    best = None
    for label, names, weights in variants:
        r = build_resolver(index, names, min_raw=0.0, dense_signal=dense_signal, weights=weights)
        recs = score(r, gold, alignment, seen)
        m = micro_prf(recs)
        mac = macro_f1(recs)
        seen_acc = micro_prf([x for x in recs if x["slice"] == "seen"])["R"]
        unseen_acc = micro_prf([x for x in recs if x["slice"] == "unseen"])["R"]
        print(f"  {label:28s} {m['F1']:9.3f} {mac:9.3f} {seen_acc:7.3f} {unseen_acc:7.3f}")
        if best is None or m["F1"] > best[1]:
            best = ((names, weights), m["F1"], recs)

    best_names, best_weights = best[0]
    print(f"\nbest variant: {'+'.join(best_names)}  weights={best_weights}  "
          f"(micro-F1={best[1]:.3f}, gate=0.85 {'PASS' if best[1] >= 0.85 else 'MISS'})")

    # ---- error analysis on best variant ----
    recs = best[2]
    wrong = [r for r in recs if not r["correct"]]
    print(f"\nmisses: {len(wrong)}/{len(recs)}")
    conf = Counter((r["gold"], r["pred"]) for r in wrong)
    print("  top confusions (gold -> pred):")
    for (g, p), n in conf.most_common(12):
        print(f"    {g:24s} -> {p:24s} x{n}")

    # ---- precision / coverage vs abstention threshold (best variant) ----
    print("\nPRECISION / COVERAGE vs abstain threshold (min_raw):")
    print(f"  {'thr':>5s} {'P':>7s} {'R':>7s} {'F1':>7s} {'cov':>7s}")
    for thr in (0.0, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80):
        r = build_resolver(index, best_names, min_raw=thr, dense_signal=dense_signal,
                           weights=best_weights)
        m = micro_prf(score(r, gold, alignment, seen))
        print(f"  {thr:5.2f} {m['P']:7.3f} {m['R']:7.3f} {m['F1']:7.3f} {m['coverage']:7.3f}")


if __name__ == "__main__":
    main()
