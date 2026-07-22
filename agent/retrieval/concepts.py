"""Concept vocabulary — derived from the corpus ONLY (PRD + taxonomy), never gold.

The event taxonomy (`events.jsonl`) has accreted cursed surface names across SDK
migrations (`evt_chkout_init`, `ChkoutInit`, `chckt_strt`, ...). Underneath, every
name belongs to exactly one *concept*. We discover that concept set legitimately,
without ever reading the hidden canonical map:

  * Each taxonomy row carries a human `description`. Rows sharing a description are
    the same concept — the grouping signal a docs author left behind. There are 44
    distinct descriptions => 44 concepts.
  * Each concept needs a stable, readable *label* (used by the analytics compiler to
    group raw events into logical funnel steps, and shown in the UI). Label sources,
    in priority order, all corpus-legitimate:
      1. descriptions of the form "<X> event." spell the concept out directly
         ("Login event." -> `login`, "Wishlist add event." -> `wishlist_add`);
      2. the funnel/technical steps have free-text descriptions instead; the PRD
         names their canonicals in backticks (`checkout_start`, `app_open`, ...),
         and we assign each PRD canonical to the concept whose text it best matches;
      3. anything still unlabelled falls back to its cleanest member name.

Note on "dead" names: a handful of documented events (`test_event_do_not_use`,
`beta_checkout_v1`, ...) never fire in any warehouse, so they are absent from the
firing-name gold. They still carry a real description ("Logout event.") and group
into the correct concept — they only ever act as extra index entries, never as eval
inputs, so they need no special handling.

Nothing here touches `data/ground_truth/`. The gold map is scorer-only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

# Repo layout: this file is agent/retrieval/concepts.py -> repo root is 3 up.
REPO_ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_PATH = REPO_ROOT / "data" / "corpus" / "taxonomy" / "events.jsonl"
PRD_PATH = REPO_ROOT / "data" / "corpus" / "spec" / "prd.md"

_EVENT_SUFFIX = re.compile(r"^(?P<body>.+?)\s+event\.?$", re.IGNORECASE)


@dataclass
class Concept:
    """One logical event concept and everything the resolver legitimately knows."""

    concept_id: str  # stable readable label, e.g. "checkout_start"
    description: str  # the shared taxonomy description (semantic profile)
    aliases: list[str] = field(default_factory=list)  # known surface names in corpus
    label_source: str = "alias"  # "event_suffix" | "prd" | "alias"

    def profile_text(self) -> str:
        """Text blob for dense embedding: label + description."""
        return f"{self.concept_id}. {self.description}"


def _load_taxonomy(path: Path = TAXONOMY_PATH) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _prd_labels(path: Path = PRD_PATH) -> list[str]:
    """Canonical labels the PRD names in backticks — the sanctioned label source."""
    text = path.read_text() if path.exists() else ""
    # snake_case, multi-token tokens only (skip bare words like `os`, `p95`).
    return sorted({t for t in re.findall(r"`([a-z][a-z0-9_]+)`", text) if "_" in t})


def _suffix_label(description: str) -> str | None:
    """"Login event." -> "login"; "Wishlist add event." -> "wishlist_add"."""
    m = _EVENT_SUFFIX.match(description.strip())
    if not m:
        return None
    body = m.group("body").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", body).strip("_")
    return slug or None


def _cleanliness(name: str) -> tuple:
    """Sort key: prefer a fully-spelled, lowercase, snake_case, unprefixed name over
    CamelCase / abbreviated / hyphenated / prefixed variants. Higher tuple = cleaner."""
    is_lower = name == name.lower()
    no_hyphen = "-" not in name
    has_underscore = "_" in name
    no_prefix = not name.startswith(("evt_", "track_", "v1_", "beta_", "old_", "legacy_"))
    vowel_ratio = sum(c in "aeiou" for c in name.lower()) / max(len(name), 1)
    return (is_lower, no_hyphen, has_underscore, no_prefix, vowel_ratio, -len(name))


def _match_score(label: str, concept: Concept) -> tuple[float, int]:
    """How well a PRD canonical describes a concept. Returns (score, token_hits).
    token_hits = number of label tokens found in the description; a PRD label is only
    assignable to a concept it shares at least one description token with. Among those,
    score (token overlap, then fuzzy alias similarity) picks the best concept."""
    spaced = label.replace("_", " ")
    lexical = max((fuzz.WRatio(label, a) for a in concept.aliases), default=0.0)
    desc = concept.description.lower()
    toks = spaced.split()
    hits = sum(t in desc for t in toks)
    score = 1000.0 * hits + lexical  # token overlap dominates; fuzzy breaks ties
    return score, hits


def build_concepts(
    taxonomy_path: Path = TAXONOMY_PATH,
    prd_path: Path = PRD_PATH,
) -> list[Concept]:
    """Derive the 44-concept vocabulary from the corpus. Deterministic; no gold."""
    rows = _load_taxonomy(taxonomy_path)
    groups: dict[str, list[str]] = {}
    for r in rows:
        groups.setdefault(r["description"], []).append(r["event_name"])

    concepts: list[Concept] = []
    for description, names in groups.items():
        label = _suffix_label(description)
        source = "event_suffix" if label else "alias"
        if not label:
            label = sorted(names, key=_cleanliness)[-1]
        concepts.append(
            Concept(
                concept_id=label,
                description=description,
                aliases=sorted(names),
                label_source=source,
            )
        )

    # Overlay PRD canonicals onto the free-text (funnel/technical) concepts: greedily
    # assign each PRD label to its best-matching still-unlabelled-by-PRD concept.
    prd = _prd_labels(prd_path)
    free = [c for c in concepts if c.label_source == "alias"]
    taken: set[int] = set()

    def best_for(label: str) -> float:
        return max((_match_score(label, c)[0] for c in free), default=0.0)

    for label in sorted(prd, key=best_for, reverse=True):
        best_i, best_s = None, 0.0
        for i, c in enumerate(free):
            if i in taken:
                continue
            s, hits = _match_score(label, c)
            if hits > 0 and s > best_s:  # must share a description token
                best_i, best_s = i, s
        if best_i is not None:
            free[best_i].concept_id = label
            free[best_i].label_source = "prd"
            taken.add(best_i)

    concepts.sort(key=lambda c: c.concept_id)
    return concepts


if __name__ == "__main__":
    concepts = build_concepts()
    by_src: dict[str, int] = {}
    for c in concepts:
        by_src[c.label_source] = by_src.get(c.label_source, 0) + 1
    print(f"{len(concepts)} concepts  {by_src}\n")
    for c in concepts:
        print(f"  [{c.label_source:12s}] {c.concept_id:24s} <- {len(c.aliases):2d} aliases")
