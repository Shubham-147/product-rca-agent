"""Writes the static, product-wide corpus (the RAG surface) + hidden canonical map.

AGENT-VISIBLE:
  spec/prd.md              intended behaviour (never mentions faults)
  taxonomy/events.jsonl    the messy data dictionary
  spec/tickets/*.md        a few synthetic support tickets (retrieval noise)
SCORER-ONLY:
  ground_truth/event_canonical_map.json   surface_name -> canonical
"""
from __future__ import annotations

import json
from pathlib import Path

from . import product
from .taxonomy import (build_taxonomy, canonical_map, dictionary_entries)

PRD = """# ShopFunnel — Product Requirements Document (PRD)

**Product:** ShopFunnel, a mobile e-commerce app (iOS + Android).
**Scope of this document:** the *intended* behaviour of every screen and of the
primary purchase funnel, plus the performance and quality bars each step is held
to. This is the source of truth for deciding whether an observed behaviour is a
**deviation from intent** (a defect) or **behaviour working as designed**.

> This PRD describes intent only. It does not describe the current health of the
> system, nor conversion rates — those are empirical properties of the event data.

---

## 1. Product overview

ShopFunnel lets a shopper discover a product, add it to a cart, and complete a
purchase in a single session. The company's north-star is completed orders; the
primary funnel below is the path to that outcome. Several screens sit *outside*
the funnel (profile, wishlist, order history, settings, search) — they support
retention and account management but are not steps on the purchase path.

The app targets a broad device base: current-generation iOS and Android
flagships, mid-tier Android, and a long tail of older, lower-end Android devices.
The experience is expected to be usable across all of them.

---

## 2. The primary conversion funnel

Each step lists its intent and the acceptance bar it is held to.

### 2.1 App open (`app_open`)
A session begins when the app is foregrounded. Every session starts here.

### 2.2 Home (`home_view`)
The home screen renders immediately after launch and presents merchandised
products. **Acceptance:** the home screen must render on every successful app
open; cold-start time to first render should meet the SLO in §4. If the home
screen fails to render, the user is stranded at launch and cannot enter the
funnel — this is a critical failure, never expected behaviour.

### 2.3 Browse / search (`product_browse`)
The user scans a product listing (merchandised list, category, or search
results). Browsing is exploratory; not every session that browses intends to buy.

### 2.4 Product detail (`product_detail_view`)
The user opens a product page with imagery, price, and description. The page must
load reliably for all users and devices; a product page that fails to load blocks
the user from adding the item and is a critical failure.

### 2.5 Add to cart (`add_to_cart`)
The user adds an item. Not all product views lead to an add — this is normal
shopping behaviour and a healthy funnel still sheds users here.

### 2.6 Cart (`cart_view`)
The user reviews items, quantities, and price. Users may edit or abandon the cart
for their own reasons; some cart abandonment is always expected.

### 2.7 Checkout (`checkout_start`)
The user begins checkout. **Acceptance:** the checkout experience must feel
instant and meet the checkout-screen latency SLO in §4. Slow checkout is a known
driver of abandonment and is treated as a defect when it exceeds the SLO.

### 2.8 Payment (`payment_submit`)
The user selects a method and submits payment. **Supported methods:** card, UPI,
wallet, cash-on-delivery (COD). **Acceptance:** all supported methods must succeed
at comparable rates; a method that silently fails for a segment of users is a
critical defect. A submitted payment should either confirm the order or surface a
clear, actionable error.

### 2.9 Order confirmed (`order_confirmed`)
The order is placed and the user sees confirmation. This is the funnel's success
event.

---

## 3. Off-funnel and optional steps (NOT defects when users leave)

These are called out explicitly so that drop-off here is **not** mistaken for a
funnel regression:

- **Upsell interstitial (`upsell_view`)** — an **optional** promotional
  interstitial that may appear between the cart and checkout. It is designed to be
  skippable, and a **high skip / drop-off rate at the upsell is expected and by
  design.** Leaving at the upsell is not a failure to reach checkout.
- **Onboarding tutorial (`tutorial_view`)** — a **skippable** first-run tutorial
  shown to some new users. Most users skip it; this is intended.
- **Profile, wishlist, order history, settings, empty-search results** — support
  screens outside the purchase funnel. Traffic to them is not part of funnel
  conversion and their usage patterns are not funnel defects.

---

## 4. Performance & quality SLOs (the bar for "deviation from intent")

An event that exceeds these bars is a candidate defect; behaviour within them is
healthy.

| Signal | Intended bar |
| :-- | :-- |
| Cold-start time to first render (`app_cold_start`) | p95 < 2000 ms |
| Checkout screen render/interaction | p95 < 2000 ms |
| General screen load | p95 < 1500 ms |
| Crash rate | rare and roughly uniform across device/OS; no single cohort should show a materially elevated rate |
| Payment success | comparable across all supported methods |

---

## 5. Instrumentation notes (why the event data is messy)

ShopFunnel's analytics have accreted over years and several SDK migrations. As a
result the raw event stream is **not clean**: the same logical event is emitted
under multiple names, casing is inconsistent, some events were renamed but the old
names still fire, and the data dictionary is incomplete in places. Consumers of
the data are expected to resolve event names to their logical meaning using the
event dictionary rather than assuming a single canonical string.

---

## 6. Non-goals (out of scope for this document)

- Merchandising and ranking logic on the home and browse screens.
- Pricing, tax, and promotion rules (coupons are handled by a separate spec).
- The recommendation model behind the upsell interstitial.
- Marketing acquisition and channel attribution. Note only that acquisition
  channels differ in user intent; a shift in the *mix* of acquired users can move
  aggregate metrics without any change in the product itself.

---

## 7. Glossary

- **Funnel step** — a screen on the primary purchase path (§2).
- **Cohort** — a set of users sharing attributes (OS, device type/age, geography,
  acquisition channel, returning vs. new).
- **Deviation from intent** — an observed behaviour that violates an acceptance
  bar in this document; the basis for calling something a defect rather than
  expected behaviour.
"""

TICKETS = [
    ("ticket_0417.md",
     "Subject: can't find my orders\n\nUser reports the order history screen was "
     "empty after placing an order last week. Advised to pull-to-refresh. Likely "
     "client cache; not reproducible on our devices."),
    ("ticket_0455.md",
     "Subject: app feels slow sometimes\n\nUser on an older Android phone says the "
     "app is 'laggy'. No specifics. Closed as cannot-reproduce."),
    ("ticket_0473.md",
     "Subject: promo code\n\nUser asking why a coupon didn't apply. Coupon had "
     "expired. Educated user. Not a bug."),
]


def write_corpus(root: Path, ground_truth_dir: Path) -> dict:
    spec = root / "spec"
    tax = root / "taxonomy"
    tickets = spec / "tickets"
    for d in (spec, tax, tickets, ground_truth_dir):
        d.mkdir(parents=True, exist_ok=True)

    (spec / "prd.md").write_text(PRD)

    forms = build_taxonomy()
    entries = dictionary_entries(forms)
    with (tax / "events.jsonl").open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    for name, body in TICKETS:
        (tickets / name).write_text(body)

    cmap = canonical_map(forms)
    (ground_truth_dir / "event_canonical_map.json").write_text(json.dumps(cmap, indent=2))

    return {
        "n_surface_forms": len(forms),
        "n_dictionary_entries": len(entries),
        "n_firing_names": len(cmap),
        "n_undocumented_firing": sum(1 for fm in forms if fm.fires and not fm.documented),
        "n_stale_documented": sum(1 for fm in forms if fm.documented and not fm.fires),
    }
