"""The cursed event taxonomy (the RAG surface) + the hidden canonical map.

We define ~40 canonical *logical* events, then scramble each into several
surface forms with real-world pathologies:
  - aliases / synonyms (checkout_start / begin_checkout / chkout_init)
  - inconsistent casing & formatting (camelCase, PascalCase, kebab-case, evt_ prefixes)
  - deprecated-but-still-firing forms
  - firing-but-undocumented forms (in the data, absent from the dictionary)
  - documented-but-stale forms (in the dictionary, never fired)

AGENT-VISIBLE output  -> taxonomy/events.jsonl   (the messy data dictionary)
SCORER-ONLY output    -> ground_truth/event_canonical_map.json  (surface -> canonical)

The taxonomy is STATIC across all instances and built from a fixed seed so it
reproduces exactly. Descriptions never reveal event health (no leakage).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

TAXONOMY_SEED = 20260718  # fixed: the taxonomy is a product-wide constant

# Canonical logical events. Funnel + off-funnel + engagement/account + technical.
# Many are distractors (retrieval noise); only some map to funnel reasoning.
CANONICAL_EVENTS: list[str] = [
    # funnel
    "app_open", "home_view", "product_browse", "product_detail_view",
    "add_to_cart", "cart_view", "checkout_start", "payment_submit", "order_confirmed",
    # search / browse
    "search_view", "search_results", "search_empty", "filter_apply", "sort_apply",
    "category_view",
    # cart / promo
    "cart_remove_item", "apply_coupon", "remove_coupon",
    # payment
    "payment_method_select", "payment_error",
    # off-funnel
    "upsell_view", "upsell_dismiss", "tutorial_view", "tutorial_skip",
    "profile_view", "wishlist_view", "wishlist_add", "wishlist_remove",
    "order_history_view", "settings_view",
    # engagement / account
    "notification_open", "push_received", "banner_click", "product_share",
    "review_view", "review_submit", "login", "logout", "signup",
    # technical
    "app_cold_start", "screen_load", "crash", "api_error", "network_timeout",
]

# Hand-authored synonyms for the events most worth making genuinely cursed.
SYNONYMS: dict[str, list[str]] = {
    "checkout_start": ["begin_checkout", "chkout_init", "start_checkout"],
    "add_to_cart": ["cart_add", "atc", "add_item_to_cart"],
    "order_confirmed": ["purchase", "order_complete", "txn_success", "order_placed"],
    "app_open": ["session_start", "app_launch"],
    "home_view": ["home_screen", "view_home"],
    "product_detail_view": ["pdp_view", "product_page", "item_detail"],
    "payment_submit": ["submit_payment", "payment_attempt"],
    "product_browse": ["browse_products", "plp_view", "list_view"],
    "crash": ["app_crash", "fatal_error", "anr"],
    "app_cold_start": ["cold_start", "app_init"],
    "screen_load": ["page_load", "view_render"],
}


@dataclass
class SurfaceForm:
    name: str
    canonical: str
    fires: bool          # does the generator emit this form into the data?
    documented: bool     # does it appear in the agent-visible dictionary?
    status: str          # "active" | "deprecated"
    weight: float        # sampling weight among a canonical's firing forms


# --- casing / formatting transforms -------------------------------------------
def _words(snake: str) -> list[str]:
    return snake.split("_")


def _camel(snake: str) -> str:
    w = _words(snake)
    return w[0] + "".join(p.capitalize() for p in w[1:])


def _pascal(snake: str) -> str:
    return "".join(p.capitalize() for p in _words(snake))


def _kebab(snake: str) -> str:
    return snake.replace("_", "-")


def _abbrev(snake: str) -> str:
    # drop interior vowels from each word > 3 chars
    out = []
    for wd in _words(snake):
        if len(wd) > 3:
            out.append(wd[0] + "".join(c for c in wd[1:] if c not in "aeiou"))
        else:
            out.append(wd)
    return "_".join(out)


_TRANSFORMS = [
    lambda s: s,                       # identity (snake)
    _camel,
    _pascal,
    _kebab,
    lambda s: "evt_" + s,
    lambda s: "track_" + s,
    _abbrev,
]


def build_taxonomy(rng: np.random.Generator | None = None) -> list[SurfaceForm]:
    """Deterministically build the full surface-form catalogue."""
    if rng is None:
        rng = np.random.default_rng(TAXONOMY_SEED)

    forms: list[SurfaceForm] = []
    seen: set[str] = set()

    for canon in CANONICAL_EVENTS:
        bases = [canon] + SYNONYMS.get(canon, [])
        # how many surface variants this canonical gets
        n_variants = int(rng.integers(3, 9))
        # candidate pool: every base under every casing/formatting transform
        candidates: list[str] = []
        for b in bases:
            for tf in _TRANSFORMS:
                candidates.append(tf(b))
        rng.shuffle(candidates)

        picked = []
        for name in candidates:
            if name in seen:
                continue
            seen.add(name)
            picked.append(name)
            if len(picked) >= n_variants:
                break
        if not picked:  # guarantee at least the canonical form
            if canon not in seen:
                seen.add(canon)
            picked = [canon]

        for i, name in enumerate(picked):
            # first form is the "primary": active, documented, main weight.
            is_primary = i == 0
            deprecated = (not is_primary) and rng.random() < 0.35
            # ~12% of non-primary firing forms are undocumented (in data, not in dict)
            documented = is_primary or rng.random() > 0.12
            fires = True
            weight = 1.0 if is_primary else float(rng.uniform(0.05, 0.4))
            forms.append(SurfaceForm(
                name=name, canonical=canon, fires=fires, documented=documented,
                status="deprecated" if deprecated else "active", weight=weight,
            ))

    # Add a handful of documented-but-stale entries (never fire) as dictionary cruft.
    stale_pool = ["legacy_view_item", "old_cart_flow", "beta_checkout_v1",
                  "deprecated_home", "test_event_do_not_use", "v1_purchase"]
    for name in stale_pool:
        if name in seen:
            continue
        seen.add(name)
        canon = str(rng.choice(CANONICAL_EVENTS))
        forms.append(SurfaceForm(name=name, canonical=canon, fires=False,
                                 documented=True, status="deprecated", weight=0.0))
    return forms


# --- accessors ----------------------------------------------------------------
def firing_forms_by_canonical(forms: list[SurfaceForm]) -> dict[str, list[SurfaceForm]]:
    out: dict[str, list[SurfaceForm]] = {}
    for f in forms:
        if f.fires:
            out.setdefault(f.canonical, []).append(f)
    return out


def canonical_map(forms: list[SurfaceForm]) -> dict[str, str]:
    """SCORER-ONLY: every firing surface name -> canonical event."""
    return {f.name: f.canonical for f in forms if f.fires}


def dictionary_entries(forms: list[SurfaceForm]) -> list[dict]:
    """AGENT-VISIBLE: the messy data dictionary (documented forms only)."""
    entries = []
    for f in forms:
        if not f.documented:
            continue
        entries.append({
            "event_name": f.name,
            "status": f.status,
            # Description states purpose only — never health. Some are terse/stale.
            "description": _describe(f.canonical),
        })
    return entries


_PURPOSE = {
    "app_open": "Fired when the app is brought to the foreground / a session begins.",
    "home_view": "User views the home screen.",
    "product_browse": "User views a product listing / browse screen.",
    "product_detail_view": "User opens a product detail page.",
    "add_to_cart": "User adds an item to the cart.",
    "cart_view": "User opens the cart.",
    "checkout_start": "User begins the checkout flow.",
    "payment_submit": "User submits a payment.",
    "order_confirmed": "Order successfully placed.",
    "upsell_view": "Optional upsell interstitial shown.",
    "tutorial_view": "First-run tutorial shown (skippable).",
    "crash": "Unhandled crash / fatal error.",
    "app_cold_start": "Cold start of the app process.",
    "screen_load": "A screen finished rendering (carries latency).",
    "payment_error": "A payment attempt failed.",
}


def _describe(canonical: str) -> str:
    return _PURPOSE.get(canonical, f"{canonical.replace('_', ' ').capitalize()} event.")
