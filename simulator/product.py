"""The simulated product: one mobile e-commerce app, one conversion funnel.

The product is STATIC across all instances (one product, one dictionary). Only
the event stream and the planted faults vary per instance.

Nothing here encodes a fault. This module describes the *intended* healthy
product — the same intent the PRD (corpus.py) communicates to the agent.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Stage:
    """One step of the primary conversion funnel.

    `base_continue` is P(reach this stage | reached previous stage) for a
    baseline (intent=1.0) user with no fault applied.
    """
    canonical: str          # canonical logical event name
    screen: str
    base_continue: float


# --- Primary conversion funnel (ordered) --------------------------------------
# app_open is the session root (continue = 1.0 given a session exists).
FUNNEL: list[Stage] = [
    Stage("app_open",          "app",             1.00),
    Stage("home_view",         "home",            0.97),
    Stage("product_browse",    "browse",          0.78),
    Stage("product_detail_view", "product_detail", 0.68),
    Stage("add_to_cart",       "product_detail",  0.42),
    Stage("cart_view",         "cart",            0.88),
    Stage("checkout_start",    "checkout",        0.72),
    Stage("payment_submit",    "payment",         0.80),
    Stage("order_confirmed",   "confirmation",    0.86),
]

FUNNEL_INDEX: dict[str, int] = {s.canonical: i for i, s in enumerate(FUNNEL)}


# --- Off-funnel screens (realism + decoys) ------------------------------------
# The two decoys are load-bearing: flagging their (by-design) drop-off is a
# false positive. The PRD explicitly states they are optional/skippable.
@dataclass(frozen=True)
class OffFunnelScreen:
    canonical: str
    screen: str
    is_decoy: bool = False
    note: str = ""


OFF_FUNNEL: list[OffFunnelScreen] = [
    OffFunnelScreen("upsell_view",   "upsell",  is_decoy=True,
                    note="Optional interstitial between cart and checkout; high skip is by design."),
    OffFunnelScreen("tutorial_view", "tutorial", is_decoy=True,
                    note="Skippable first-run tutorial; most users skip it."),
    OffFunnelScreen("profile_view",  "profile"),
    OffFunnelScreen("wishlist_view", "wishlist"),
    OffFunnelScreen("order_history_view", "order_history"),
    OffFunnelScreen("search_empty",  "search"),
    OffFunnelScreen("settings_view", "settings"),
]

DECOY_SCREENS: list[str] = [s.screen for s in OFF_FUNNEL if s.is_decoy]

# Supported payment methods (one of these is the target of payment_failure).
PAYMENT_METHODS: list[str] = ["card", "upi", "wallet", "cod"]

# Technical / signal events the app emits (not funnel steps).
TECH_EVENTS: list[str] = [
    "app_cold_start", "screen_load", "crash", "api_error",
    "payment_error", "network_timeout",
]

# Intended SLOs the PRD communicates (used by the agent to recognise a
# *regression* as a deviation from intent). Latencies in milliseconds.
SLO = {
    "cold_start_p95_ms": 2000,
    "checkout_screen_p95_ms": 2000,
    "screen_load_p95_ms": 1500,
}
