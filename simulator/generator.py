"""The simulation engine: population -> sessions -> funnel walk -> events.

Emits events using the *cursed* surface names so the taxonomy matters. Returns
raw user + event records plus the set of fault-affected user IDs (for Gold).

Design notes baked in here:
  - Regression is TEMPORAL: the fault activates at `changepoint_day`.
  - The marketing-spike cohort is concentrated AFTER the changepoint, so a
    confounder-trap instance still shows an aggregate dip with an *innocent*
    cause (traffic-mix shift), keeping the task symmetric with fault instances.
  - Simpson: an opposite, silent improvement in another segment cancels the
    aggregate, forcing the agent to segment before concluding.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from . import product
from .faults import make_fault
from .personas import PERSONAS, PERSONA_BY_NAME, sample_attributes
from .schemas import FaultType, InstanceConfig
from .taxonomy import SurfaceForm, firing_forms_by_canonical

BASE_DATE = datetime(2026, 6, 1)

# baseline screen-load latency by screen (ms), before persona/fault scaling
_BASE_LATENCY = {
    "app": 300, "home": 600, "browse": 700, "product_detail": 800,
    "cart": 500, "checkout": 900, "payment": 1000, "confirmation": 700,
    "upsell": 500, "tutorial": 400, "profile": 500, "wishlist": 500,
    "order_history": 600, "search": 700, "settings": 400,
}


class _Emitter:
    """Columnar event sink (fast append)."""
    def __init__(self):
        self.cols: dict[str, list] = {k: [] for k in (
            "user_id", "session_id", "event_ts", "event_name", "canonical",
            "screen", "latency_ms", "is_crash", "payment_method")}

    def add(self, **kw):
        c = self.cols
        for k in c:
            c[k].append(kw.get(k))


def _pick_form(rng, forms: list[SurfaceForm]) -> SurfaceForm:
    w = np.array([f.weight for f in forms], dtype=float)
    w = w / w.sum()
    return forms[int(rng.choice(len(forms), p=w))]


def _emit_event(rng, em, forms_by_canon, *, user_id, session_id, ts, canonical,
                screen, latency_ms=None, is_crash=False, payment_method=None):
    form = _pick_form(rng, forms_by_canon[canonical])
    em.add(user_id=user_id, session_id=session_id, event_ts=ts, event_name=form.name,
           canonical=canonical, screen=screen,
           latency_ms=None if latency_ms is None else int(latency_ms),
           is_crash=bool(is_crash),
           payment_method=payment_method)


def generate(cfg: InstanceConfig, forms: list[SurfaceForm]) -> dict:
    rng = np.random.default_rng(cfg.seed)
    fault = make_fault(cfg)
    forms_by_canon = firing_forms_by_canonical(forms)

    # ---- persona mix ----
    mix = cfg.persona_mix or {p.name: p.share for p in PERSONAS}
    names = list(mix.keys())
    probs = np.array([mix[n] for n in names], dtype=float)
    probs = probs / probs.sum()

    # ---- population ----
    users: list[dict] = []
    for i in range(cfg.n_users):
        pname = str(rng.choice(names, p=probs))
        persona = PERSONA_BY_NAME[pname]
        attrs = sample_attributes(rng, persona)
        uid = f"{cfg.instance_id}_u{i:05d}"
        attrs["user_id"] = uid
        # acquisition: spike cohort acquired in the regression window
        if pname == "marketing_spike_bouncer":
            acq_day = int(rng.integers(cfg.changepoint_day, cfg.window_days))
        else:
            acq_day = int(rng.integers(0, cfg.window_days))
        attrs["acquired_ts"] = BASE_DATE + timedelta(days=acq_day,
                                                      seconds=int(rng.integers(0, 86400)))
        attrs["_persona"] = persona
        attrs["_acq_day"] = acq_day
        users.append(attrs)

    em = _Emitter()
    ft = fault.fault_type
    demographic = ft not in (FaultType.NONE, FaultType.PAYMENT_FAILURE)
    cohort_members: set[str] = set()   # demographic cohort membership
    reg_active: set[str] = set()       # had >=1 session in the regression window
    method_reg: dict[str, set] = {}    # methods used in regression sessions

    for u in users:
        persona = u["_persona"]
        uid = u["user_id"]
        if demographic and fault.in_cohort(u):
            cohort_members.add(uid)
        n_sessions = int(rng.poisson(persona.sessions_lambda))
        for s in range(n_sessions):
            lo = min(u["_acq_day"], cfg.window_days - 1)
            day = int(rng.integers(lo, cfg.window_days))
            if day >= cfg.changepoint_day:
                reg_active.add(uid)
            method = _simulate_session(rng, em, forms_by_canon, u, s, day, fault, cfg)
            if method and day >= cfg.changepoint_day:
                method_reg.setdefault(uid, set()).add(method)

    # The SCORED affected set: cohort ∩ regression activity (decoupled from the
    # stochastic drops). For payment, membership is by method used in regression.
    if ft == FaultType.NONE:
        affected: set[str] = set()
    elif ft == FaultType.PAYMENT_FAILURE:
        affected = {uid for uid, ms in method_reg.items() if fault.payment_method in ms}
    else:
        affected = {uid for uid in cohort_members if uid in reg_active}

    user_rows = [{k: v for k, v in u.items() if not k.startswith("_")} for u in users]
    return {"users": user_rows, "events": em.cols, "affected_user_ids": sorted(affected)}


def _simulate_session(rng, em, forms_by_canon, u, s_idx, day, fault, cfg):
    """Simulate one session; return the payment method used (or None)."""
    persona = u["_persona"]
    uid = u["user_id"]
    sid = f"{uid}_s{s_idx:03d}"
    session_method = None
    t = BASE_DATE + timedelta(days=day, seconds=int(rng.integers(0, 86400)))

    def step_ts():
        nonlocal t
        t = t + timedelta(seconds=int(rng.integers(2, 20)))
        return t

    intent = persona.intent
    # Simpson: a silent, compensating improvement in another segment (iOS) cancels
    # the aggregate, forcing the agent to segment before concluding.
    simpson_mult = 1.0
    if cfg.is_simpson and day >= cfg.changepoint_day and u["os"].startswith("iOS"):
        simpson_mult = 1.15

    # ---- app_open + cold start (always) ----
    _emit_event(rng, em, forms_by_canon, user_id=uid, session_id=sid, ts=t,
                canonical="app_open", screen="app")
    cs_latency = _BASE_LATENCY["app"] * persona.latency_scale * rng.uniform(0.8, 1.6)
    _emit_event(rng, em, forms_by_canon, user_id=uid, session_id=sid, ts=step_ts(),
                canonical="app_cold_start", screen="app", latency_ms=cs_latency)

    # ---- tutorial (new users, skippable decoy) ----
    if not u["is_returning"] and rng.random() < 0.6:
        _emit_event(rng, em, forms_by_canon, user_id=uid, session_id=sid, ts=step_ts(),
                    canonical="tutorial_view", screen="tutorial")
        _emit_event(rng, em, forms_by_canon, user_id=uid, session_id=sid, ts=step_ts(),
                    canonical="tutorial_skip", screen="tutorial")

    # ---- walk the funnel from home_view onward ----
    for i in range(1, len(product.FUNNEL)):
        stage = product.FUNNEL[i]

        # crash check on the screen we are about to load
        crash_p = persona.crash_propensity + fault.extra_crash_prob(stage.screen, u, day)
        if rng.random() < crash_p:
            _emit_event(rng, em, forms_by_canon, user_id=uid, session_id=sid, ts=step_ts(),
                        canonical="crash", screen=stage.screen, is_crash=True)
            return session_method

        # continue prob = baseline (intent-adjusted) * simpson, minus the fault's
        # additive penalty on this step. Severity == the local drop this induces.
        cont = stage.base_continue ** (1.0 / max(0.2, intent)) * simpson_mult
        cont -= fault.continue_penalty(stage.canonical, u, day)
        cont = float(np.clip(cont, 0.0, 0.995))

        if rng.random() > cont:
            if fault.emits_error_on_drop(stage.canonical) and fault.active(u, day):
                _emit_event(rng, em, forms_by_canon, user_id=uid, session_id=sid, ts=step_ts(),
                            canonical="api_error", screen=stage.screen)
            return session_method  # dropped here (home never rendered, screen dead, etc.)

        # payment: pick a method and emit the selection BEFORE the submit
        method = None
        if stage.canonical == "payment_submit":
            method = session_method = _pick_payment(rng, persona)
            _emit_event(rng, em, forms_by_canon, user_id=uid, session_id=sid, ts=step_ts(),
                        canonical="payment_method_select", screen="payment",
                        payment_method=method)

        # emit the stage event + a screen_load carrying latency
        latency = _BASE_LATENCY.get(stage.screen, 600) * persona.latency_scale \
            * rng.uniform(0.7, 1.5) + fault.extra_latency_ms(stage.screen, u, day)
        _emit_event(rng, em, forms_by_canon, user_id=uid, session_id=sid, ts=step_ts(),
                    canonical=stage.canonical, screen=stage.screen, payment_method=method)
        _emit_event(rng, em, forms_by_canon, user_id=uid, session_id=sid, ts=step_ts(),
                    canonical="screen_load", screen=stage.screen, latency_ms=latency)

        # ---- upsell interstitial (decoy) after cart_view ----
        if stage.canonical == "cart_view" and rng.random() < 0.5:
            _emit_event(rng, em, forms_by_canon, user_id=uid, session_id=sid, ts=step_ts(),
                        canonical="upsell_view", screen="upsell")
            if rng.random() < 0.3:         # by-design drop at the optional upsell
                return session_method
            _emit_event(rng, em, forms_by_canon, user_id=uid, session_id=sid, ts=step_ts(),
                        canonical="upsell_dismiss", screen="upsell")

        # ---- payment result: block the order for the failing method ----
        if stage.canonical == "payment_submit" and \
                rng.random() < fault.payment_block_prob(method, u, day):
            _emit_event(rng, em, forms_by_canon, user_id=uid, session_id=sid, ts=step_ts(),
                        canonical="payment_error", screen="payment", payment_method=method)
            return session_method

    return session_method


def _pick_payment(rng, persona) -> str:
    keys = list(persona.payment_mix.keys())
    p = np.array([persona.payment_mix[k] for k in keys], dtype=float)
    if p.sum() == 0:
        return "card"
    p = p / p.sum()
    return str(rng.choice(keys, p=p))
