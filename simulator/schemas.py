"""Typed contracts shared across the simulator, the scorer, and (later) the agent.

`Hypothesis` is the agent->scorer/UI contract. `Gold` is the held-out answer.
`InstanceConfig` fully determines a generated instance (seed + what to plant).
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

# The closed set of mechanisms — makes attribution objectively scorable.
MechanismType = Literal[
    "dead_screen", "checkout_latency", "cold_start",
    "crash_concentration", "payment_failure", "innocent_dropoff",
]


class FaultType(str, Enum):
    NONE = "none"                     # confounder-trap: nothing to fix
    DEAD_SCREEN = "dead_screen"
    CHECKOUT_LATENCY = "checkout_latency"
    COLD_START = "cold_start"
    CRASH_CONCENTRATION = "crash_concentration"
    PAYMENT_FAILURE = "payment_failure"


# --- agent output contract ----------------------------------------------------
class Evidence(BaseModel):
    claim: str
    sql: str = ""
    result_summary: str = ""


class Hypothesis(BaseModel):
    mechanism_type: MechanismType
    mechanism: str
    affected_cohort: str = Field(
        ..., description="SQL WHERE over whitelisted cols; compiled to a user-ID set")
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    confounders_considered: list[str] = Field(default_factory=list)


# --- held-out ground truth ----------------------------------------------------
class Gold(BaseModel):
    instance_id: str
    seed: int
    has_fault: bool
    fault_type: str                            # FaultType value
    affected_user_ids: list[str] = Field(default_factory=list)
    affected_cohort_predicate: str = ""        # human-readable, for the judge
    severity_pp_target: float = 0.0            # requested effect size
    severity_pp_realised: float = 0.0          # measured after generation
    confounder_type: str = "none"              # "device_age" | "low_intent" | "simpson" | "none"
    is_confounder_trap: bool = False
    is_simpson: bool = False
    decoy_screens: list[str] = Field(default_factory=list)
    acceptable_mechanisms: list[str] = Field(default_factory=list)
    changepoint_day: int = 0
    persona_mix: dict[str, float] = Field(default_factory=dict)
    notes: str = ""


# --- what to generate ---------------------------------------------------------
class InstanceConfig(BaseModel):
    instance_id: str
    seed: int
    n_users: int = 6000
    window_days: int = 28
    changepoint_day: int = 14                  # fault activates here (regression period)
    fault_type: FaultType = FaultType.NONE
    severity_pp: float = 8.0                    # target conversion impact (percentage points)
    cohort_predicate: Optional[str] = None      # human-readable; resolved in faults.py
    is_confounder_trap: bool = False
    is_simpson: bool = False
    persona_mix: Optional[dict[str, float]] = None  # overrides default shares
