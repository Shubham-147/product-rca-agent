"""Synthetic, deliberately inconsistent product-event taxonomy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_CANONICAL_EVENTS = [
    ("app_open", "Application process opened", "lifecycle"),
    ("splash_view", "Splash screen displayed", "screen"),
    ("home_render", "Home screen rendered", "screen"),
    ("search_view", "Search screen displayed", "screen"),
    ("search_submit", "A search query was submitted", "interaction"),
    ("product_view", "Product detail screen displayed", "screen"),
    ("add_to_cart", "Product added to cart", "commerce"),
    ("cart_view", "Cart screen displayed", "screen"),
    ("checkout_start", "Checkout flow started", "commerce"),
    ("shipping_view", "Shipping screen displayed", "screen"),
    ("shipping_submit", "Shipping details submitted", "commerce"),
    ("payment_view", "Payment screen displayed", "screen"),
    ("payment_submit", "Payment attempt submitted", "commerce"),
    ("payment_failure", "Payment provider rejected or errored", "error"),
    ("order_complete", "Order successfully created", "commerce"),
    ("confirmation_view", "Order confirmation displayed", "screen"),
    ("recommendations_view", "Post-purchase recommendations displayed", "screen"),
    ("loyalty_view", "Loyalty screen displayed", "screen"),
    ("session_end", "Synthetic end-of-session marker", "lifecycle"),
    ("app_crash", "Application crashed", "error"),
    ("api_error", "Backend request failed", "error"),
    ("checkout_slow", "Checkout response exceeded latency threshold", "performance"),
    ("cold_start", "Application launched without a warm process", "performance"),
    ("promo_interstitial_view", "Optional promotion interstitial displayed", "screen"),
    ("promo_skip", "Optional promotion was intentionally skipped", "interaction"),
    ("filter_apply", "Search filter applied", "interaction"),
    ("wishlist_add", "Product added to wishlist", "interaction"),
    ("coupon_apply", "Coupon code applied", "commerce"),
    ("address_edit", "Saved address edited", "interaction"),
    ("support_open", "Support entry point opened", "interaction"),
    ("network_retry", "A failed network request was retried", "performance"),
    ("login_success", "User authentication succeeded", "identity"),
    ("logout", "User signed out", "identity"),
    ("experiment_exposure", "User exposed to an experiment", "experiment"),
]

_ALIASES = {
    "app_open": ["appOpen", "launch_app"],
    "home_render": ["homeRendered", "hm_rndr"],
    "search_view": ["searchScreen", "srch_view"],
    "product_view": ["productViewed", "pdp_view"],
    "add_to_cart": ["addToCart", "atc"],
    "cart_view": ["viewCart", "crt_view"],
    "checkout_start": ["begin_checkout", "chkout_init"],
    "shipping_view": ["shippingScreen", "ship_pg"],
    "payment_view": ["paymentScreen", "pay_view"],
    "payment_submit": ["submitPayment", "pay_submit"],
    "payment_failure": ["paymentFailed", "pay_fail"],
    "order_complete": ["purchase", "orderCompleted"],
    "app_crash": ["appCrash", "fatal_err"],
    "session_end": ["sessionEnd"],
}

_DEAD_EVENTS = [
    ("legacy_quick_buy", "Retired one-tap purchase event", "commerce"),
    ("old_rewards_banner", "Removed rewards banner impression", "screen"),
    ("beta_ar_tryon", "Abandoned AR try-on experiment", "experiment"),
    ("fax_receipt_request", "Unused receipt delivery option", "interaction"),
]


def build_taxonomy() -> list[dict[str, Any]]:
    """Return 60-ish taxonomy records containing aliases and dead definitions."""
    records: list[dict[str, Any]] = []
    descriptions: dict[str, tuple[str, str]] = {}
    for name, description, category in _CANONICAL_EVENTS:
        descriptions[name] = (description, category)
        records.append(
            {
                "event_name": name,
                "description": description,
                "category": category,
                "is_alias_of": None,
                "is_dead": False,
            }
        )
    for canonical, aliases in _ALIASES.items():
        description, category = descriptions[canonical]
        for alias in aliases:
            records.append(
                {
                    "event_name": alias,
                    "description": f"Alias for {canonical}: {description}",
                    "category": category,
                    "is_alias_of": canonical,
                    "is_dead": False,
                }
            )
    for name, description, category in _DEAD_EVENTS:
        records.append(
            {
                "event_name": name,
                "description": description,
                "category": category,
                "is_alias_of": None,
                "is_dead": True,
            }
        )
    return records


def write_taxonomy(output_path: Path) -> list[dict[str, Any]]:
    """Write the taxonomy as JSON and return its records."""
    records = build_taxonomy()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    return records

