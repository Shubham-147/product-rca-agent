"""The six user personas.

A persona is (attribute distribution) + (behavioural parameters). Personas are
how we get realistic heterogeneity AND how confounders become *structural*
rather than decorative:

  - Old-Device Android carries the device-age confounder: at BASELINE (no fault)
    these users both crash more AND retain/convert less, independently. That is
    the "crashers churn, but device-age is the real driver" trap.
  - Marketing-Spike Bouncer is the low-intent decoy cohort (noise, not a fault).

CRITICAL: the `persona` label is NEVER exposed to the agent (see writer.py). The
agent must rediscover cohorts from real attributes (os, device_age_months, ...).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class Persona:
    name: str
    share: float                       # fraction of the population (before per-instance tweaks)
    # attribute samplers expressed as categorical dists / ranges
    os_dist: dict[str, float]
    device_type_dist: dict[str, float]
    device_age_range: tuple[int, int]  # months, inclusive
    geo_dist: dict[str, float]
    channel_dist: dict[str, float]
    p_returning: float
    # behaviour
    intent: float                      # multiplies funnel continue-probabilities
    sessions_lambda: float             # mean sessions over the window (Poisson)
    crash_propensity: float            # per-screen-load crash probability at baseline
    latency_scale: float               # multiplies baseline screen latency
    payment_mix: dict[str, float]      # preferred payment methods


PERSONAS: list[Persona] = [
    Persona(
        name="loyal_converter", share=0.24,
        os_dist={"iOS 17": 0.5, "Android 14": 0.35, "Android 13": 0.15},
        device_type_dist={"flagship": 0.7, "mid": 0.3},
        device_age_range=(0, 18),
        geo_dist={"US": 0.5, "IN": 0.3, "EU": 0.2},
        channel_dist={"organic": 0.6, "referral": 0.25, "paid": 0.15},
        p_returning=0.9, intent=1.25, sessions_lambda=6.0,
        crash_propensity=0.002, latency_scale=0.9,
        payment_mix={"card": 0.5, "upi": 0.3, "wallet": 0.2, "cod": 0.0},
    ),
    Persona(
        name="bargain_hunter", share=0.20,
        os_dist={"Android 14": 0.4, "Android 13": 0.3, "iOS 17": 0.3},
        device_type_dist={"mid": 0.6, "flagship": 0.25, "budget": 0.15},
        device_age_range=(6, 30),
        geo_dist={"IN": 0.5, "US": 0.3, "EU": 0.2},
        channel_dist={"paid": 0.4, "organic": 0.35, "referral": 0.25},
        p_returning=0.75, intent=0.95, sessions_lambda=5.0,
        crash_propensity=0.004, latency_scale=1.0,
        payment_mix={"upi": 0.4, "card": 0.25, "cod": 0.25, "wallet": 0.1},
    ),
    Persona(
        name="window_shopper", share=0.20,
        os_dist={"iOS 17": 0.4, "Android 14": 0.35, "Android 13": 0.25},
        device_type_dist={"mid": 0.5, "flagship": 0.35, "budget": 0.15},
        device_age_range=(0, 30),
        geo_dist={"US": 0.4, "EU": 0.35, "IN": 0.25},
        channel_dist={"organic": 0.5, "paid": 0.3, "referral": 0.2},
        p_returning=0.55, intent=0.6, sessions_lambda=3.0,
        crash_propensity=0.004, latency_scale=1.0,
        payment_mix={"card": 0.45, "upi": 0.3, "wallet": 0.2, "cod": 0.05},
    ),
    # --- carries the device-age confounder ---
    Persona(
        name="old_device_android", share=0.16,
        os_dist={"Android 12": 0.45, "Android 11": 0.35, "Android 10": 0.20},
        device_type_dist={"budget": 0.6, "mid": 0.4},
        device_age_range=(24, 54),
        geo_dist={"IN": 0.55, "US": 0.2, "EU": 0.25},
        channel_dist={"paid": 0.45, "organic": 0.35, "referral": 0.2},
        # low intent AND high crash — the two co-move at baseline, WITHOUT a fault.
        p_returning=0.5, intent=0.7, sessions_lambda=2.5,
        crash_propensity=0.020, latency_scale=1.35,
        payment_mix={"upi": 0.45, "cod": 0.35, "card": 0.15, "wallet": 0.05},
    ),
    # --- low-intent decoy cohort (noise, not a fault) ---
    Persona(
        name="marketing_spike_bouncer", share=0.12,
        os_dist={"Android 13": 0.4, "Android 14": 0.3, "iOS 17": 0.3},
        device_type_dist={"mid": 0.5, "budget": 0.35, "flagship": 0.15},
        device_age_range=(3, 30),
        geo_dist={"IN": 0.45, "US": 0.35, "EU": 0.2},
        channel_dist={"paid": 1.0},   # acquired entirely via the paid spike
        p_returning=0.1, intent=0.35, sessions_lambda=1.4,
        crash_propensity=0.004, latency_scale=1.05,
        payment_mix={"upi": 0.4, "card": 0.3, "cod": 0.2, "wallet": 0.1},
    ),
    Persona(
        name="slow_network_intl", share=0.08,
        os_dist={"Android 13": 0.4, "iOS 17": 0.35, "Android 12": 0.25},
        device_type_dist={"mid": 0.55, "budget": 0.3, "flagship": 0.15},
        device_age_range=(6, 40),
        geo_dist={"SEA": 0.5, "LATAM": 0.3, "EU": 0.2},
        channel_dist={"organic": 0.5, "paid": 0.3, "referral": 0.2},
        p_returning=0.6, intent=0.85, sessions_lambda=3.5,
        crash_propensity=0.006, latency_scale=1.8,   # slow network -> high latency
        payment_mix={"card": 0.4, "upi": 0.3, "wallet": 0.2, "cod": 0.1},
    ),
]

PERSONA_BY_NAME: dict[str, Persona] = {p.name: p for p in PERSONAS}


def _sample_cat(rng: np.random.Generator, dist: dict[str, float]) -> str:
    keys = list(dist.keys())
    probs = np.array([dist[k] for k in keys], dtype=float)
    probs = probs / probs.sum()
    return str(rng.choice(keys, p=probs))


def sample_attributes(rng: np.random.Generator, persona: Persona) -> dict:
    """Draw one user's concrete attributes from the persona's distributions."""
    return {
        "persona": persona.name,   # STORED SCORER-SIDE ONLY; stripped from the warehouse
        "os": _sample_cat(rng, persona.os_dist),
        "device_type": _sample_cat(rng, persona.device_type_dist),
        "device_age_months": int(rng.integers(persona.device_age_range[0],
                                               persona.device_age_range[1] + 1)),
        "geo": _sample_cat(rng, persona.geo_dist),
        "channel": _sample_cat(rng, persona.channel_dist),
        "is_returning": bool(rng.random() < persona.p_returning),
    }
