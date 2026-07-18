"""The fault library + the cohort each fault targets.

A fault modifies the affected cohort's behaviour ONLY during the regression
period (event day >= changepoint_day), so both period-over-period and
cohort-vs-rest comparisons reveal it.

Cohorts are deliberately expressed over REAL, agent-visible attributes and are
chosen to overlap several personas — so no single visible column trivially
separates fault users from innocent ones (checks.py verifies this).

The `persona`/confounder structure lives in personas.py (Old-Device users crash
and churn at baseline). A confounder-trap instance plants FaultType.NONE: the
correlation exists, but the correct answer is "no actionable fault".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .schemas import FaultType, InstanceConfig

# Human-readable + python predicate for each fault's default cohort.
# (predicate string is for the judge; the callable is what the generator uses.)
_DEFAULT_COHORTS: dict[FaultType, tuple[str, Callable[[dict], bool]]] = {
    FaultType.DEAD_SCREEN: (
        "os = 'Android 12'",
        lambda a: a["os"] == "Android 12"),
    FaultType.CHECKOUT_LATENCY: (
        # a high-reach cohort so the late-funnel step has a stable denominator
        "os = 'iOS 17'",
        lambda a: a["os"] == "iOS 17"),
    FaultType.COLD_START: (
        "os IN ('Android 10', 'Android 11')",
        lambda a: a["os"] in ("Android 10", "Android 11")),
    FaultType.CRASH_CONCENTRATION: (
        "os = 'Android 12' AND device_age_months > 24",
        lambda a: a["os"] == "Android 12" and a["device_age_months"] > 24),
    FaultType.PAYMENT_FAILURE: (
        "payment_method = 'upi'",           # event-level predicate (see note in docs)
        lambda a: True),                    # membership is decided per payment attempt
}

# Acceptable mechanism labels the scorer will credit for each fault.
ACCEPTABLE_MECHANISMS: dict[FaultType, list[str]] = {
    FaultType.NONE: ["innocent_dropoff"],
    FaultType.DEAD_SCREEN: ["dead_screen"],
    FaultType.CHECKOUT_LATENCY: ["checkout_latency"],
    FaultType.COLD_START: ["cold_start"],
    FaultType.CRASH_CONCENTRATION: ["crash_concentration"],
    FaultType.PAYMENT_FAILURE: ["payment_failure"],
}


# The funnel stage each fault penalises, and the (from -> to) transition whose
# local conversion drop DEFINES the severity (measured in checks.py).
PENALTY_STAGE: dict[FaultType, str] = {
    FaultType.DEAD_SCREEN: "product_detail_view",
    FaultType.CHECKOUT_LATENCY: "payment_submit",
    FaultType.COLD_START: "home_view",
}
STEP_METRIC: dict[FaultType, tuple[str, str]] = {
    FaultType.DEAD_SCREEN: ("product_browse", "product_detail_view"),
    FaultType.CHECKOUT_LATENCY: ("checkout_start", "payment_submit"),
    FaultType.COLD_START: ("app_open", "home_view"),
    FaultType.PAYMENT_FAILURE: ("payment_submit", "order_confirmed"),
    # crash is measured as a crash-RATE delta, not a step transition
}


@dataclass
class Fault:
    """Runtime fault object the generator consults at each decision point.

    Severity is an ADDITIVE penalty (`strength` = severity_pp/100) applied to the
    affected step's continue-probability, so the realised local-step drop ~ target
    and is directly calibratable. The scored `affected` user set is computed
    separately (cohort ∩ regression activity), not from stochastic drops.
    """
    fault_type: FaultType
    cohort_predicate: str
    _in_cohort: Callable[[dict], bool]
    strength: float                    # severity_pp / 100
    changepoint_day: int
    payment_method: str = "upi"        # target of payment_failure

    # --- membership / timing --------------------------------------------------
    def in_cohort(self, attrs: dict) -> bool:
        return self._in_cohort(attrs)

    def active(self, attrs: dict, day: int) -> bool:
        if self.fault_type == FaultType.NONE:
            return False
        return day >= self.changepoint_day and self.in_cohort(attrs)

    # --- effect hooks (called by generator.py) --------------------------------
    def continue_penalty(self, canonical: str, attrs: dict, day: int) -> float:
        """Additive reduction of the continue-prob into `canonical` for the cohort."""
        if self.active(attrs, day) and PENALTY_STAGE.get(self.fault_type) == canonical:
            return self.strength
        return 0.0

    def emits_error_on_drop(self, canonical: str) -> bool:
        # dead_screen leaves a visible api_error at the broken screen
        return self.fault_type == FaultType.DEAD_SCREEN and canonical == "product_detail_view"

    def extra_latency_ms(self, screen: str, attrs: dict, day: int) -> float:
        if self.fault_type == FaultType.CHECKOUT_LATENCY and screen == "checkout" \
                and self.active(attrs, day):
            return 2500.0 + self.strength * 12000.0
        return 0.0

    def extra_crash_prob(self, screen: str, attrs: dict, day: int) -> float:
        if self.fault_type == FaultType.CRASH_CONCENTRATION and self.active(attrs, day) \
                and screen in ("product_detail", "checkout", "cart"):
            # ~3 exposed screens -> per-session crash rate rises ~3x this; scale
            # so the realised crash-rate increase (pp) tracks the target severity.
            return min(0.3, self.strength * 1.0)
        return 0.0

    def payment_block_prob(self, method: str, attrs: dict, day: int) -> float:
        """Prob an order is blocked for the target method in the regression window."""
        if self.fault_type == FaultType.PAYMENT_FAILURE and method == self.payment_method \
                and day >= self.changepoint_day:
            return min(0.98, self.strength / 0.86)   # ~= target-pp drop on P(order|pay)
        return 0.0


def make_fault(cfg: InstanceConfig) -> Fault:
    ft = cfg.fault_type
    if ft == FaultType.NONE:
        return Fault(FaultType.NONE, "n/a", lambda a: False, 0.0, cfg.changepoint_day)
    predicate, fn = _DEFAULT_COHORTS[ft]
    if cfg.cohort_predicate:
        predicate = cfg.cohort_predicate  # human-readable override only
    return Fault(
        fault_type=ft,
        cohort_predicate=predicate,
        _in_cohort=fn,
        strength=cfg.severity_pp / 100.0,
        changepoint_day=cfg.changepoint_day,
    )
