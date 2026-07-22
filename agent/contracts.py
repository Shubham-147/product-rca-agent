"""Typed contracts at every boundary (design tenet #2).

The agent forms *intent* as validated Pydantic structures; the analytics compiler
turns that intent into SQL (design decision D8). The most important structure is the
**Cohort DSL** (D3): the agent names an affected cohort as a predicate AST over a
fixed whitelist of user attributes, never as a raw SQL string. This is:
  * safe — no SQL parsing, no injection surface (values are escaped, columns whitelisted);
  * deterministic & UI-renderable;
  * exactly scorable — two cohorts normalize to a canonical form for set comparison.

`Hypothesis` is re-exported from the simulator so the agent and the scorer share one
definition. NOTE: the simulator's `Hypothesis.affected_cohort` is still a `str` (a SQL
WHERE predicate) — the shared-schema migration to `Cohort` is coordinated with Shubham.
Until then the agent builds a `Cohort` and emits `cohort.to_sql()` into that field, so
the existing scorer keeps working unchanged. `Cohort.to_sql()` is the bridge.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Union

from pydantic import BaseModel, Field, field_validator

from simulator.schemas import Evidence, Gold, Hypothesis  # shared definitions

__all__ = ["Evidence", "Gold", "Hypothesis", "AgentHypothesis", "Cohort", "Condition",
           "Period", "ToolError", "MECHANISM_TYPES"]

# The mechanism vocabulary the agent must choose from (matches simulator FaultType).
MechanismType = Literal[
    "dead_screen", "checkout_latency", "cold_start", "crash_concentration",
    "payment_failure", "innocent_dropoff",
]
MECHANISM_TYPES = list(MechanismType.__args__)

# The only columns a cohort predicate may reference — matches the task whitelist and
# the warehouse `users` schema. Anything else is a validation error.
Col = Literal["os", "device_type", "device_age_months", "geo", "channel", "is_returning"]
Op = Literal["eq", "ne", "lt", "le", "gt", "ge", "in"]

_SQL_OP = {"eq": "=", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}


class Period(str, Enum):
    """The comparison windows. `pre` = baseline (day < changepoint), `post` = recent."""

    pre = "pre"
    post = "post"
    both = "both"


def _sql_literal(v: Union[str, int, bool]) -> str:
    """Render a Python value as a safe SQL literal (strings single-quote-escaped)."""
    if isinstance(v, bool):  # bool before int — bool is an int subclass
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


class Condition(BaseModel):
    col: Col
    op: Op
    value: Union[str, int, bool, list[Union[str, int]]]

    @field_validator("value")
    @classmethod
    def _list_only_with_in(cls, v, info):
        return v  # op/value coherence checked in to_sql (typed error there)

    def to_sql(self) -> str:
        if self.op == "in":
            if not isinstance(self.value, list) or not self.value:
                raise ValueError("op 'in' requires a non-empty list value")
            items = ", ".join(_sql_literal(x) for x in self.value)
            return f"{self.col} IN ({items})"
        if isinstance(self.value, list):
            raise ValueError(f"op '{self.op}' cannot take a list value")
        return f"{self.col} {_SQL_OP[self.op]} {_sql_literal(self.value)}"

    def _norm_key(self) -> tuple:
        val = tuple(sorted(map(str, self.value))) if isinstance(self.value, list) else str(self.value)
        return (self.col, self.op, val)


class Cohort(BaseModel):
    """An AND of conditions, with an optional OR group (`any`). Empty cohort = all users."""

    all: list[Condition] = Field(default_factory=list)
    any: list[Condition] = Field(default_factory=list)

    def to_sql(self) -> str:
        """Compile to a WHERE predicate. Empty => '1=1' (the whole population)."""
        parts: list[str] = [c.to_sql() for c in self.all]
        if self.any:
            parts.append("(" + " OR ".join(c.to_sql() for c in self.any) + ")")
        return " AND ".join(parts) if parts else "1=1"

    def normalized(self) -> tuple:
        """Order-independent key for exact cohort comparison / dedup."""
        return (
            tuple(sorted(c._norm_key() for c in self.all)),
            tuple(sorted(c._norm_key() for c in self.any)),
        )

    def __str__(self) -> str:
        return self.to_sql()


class AgentHypothesis(BaseModel):
    """What the agent emits: like `Hypothesis`, but `affected_cohort` is the typed
    Cohort DSL, not a SQL string. Validated at the model boundary (a malformed cohort
    is a caught error the agent repairs), then bridged to the simulator `Hypothesis`
    (which the scorer consumes) via `.to_hypothesis()`."""

    mechanism_type: MechanismType
    mechanism: str
    affected_cohort: Cohort
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = 0.5
    confounders_considered: list[str] = Field(default_factory=list)

    def to_hypothesis(self) -> Hypothesis:
        return Hypothesis(
            mechanism_type=self.mechanism_type,
            mechanism=self.mechanism,
            affected_cohort=self.affected_cohort.to_sql(),  # DSL -> SQL bridge
            evidence=self.evidence,
            confidence=self.confidence,
            confounders_considered=self.confounders_considered,
        )


class ToolError(BaseModel):
    """A typed, recoverable error a tool hands back to the agent (never an exception).

    `hint` tells the model how to fix its call so it can retry (design tenet #7)."""

    error: str
    hint: str = ""

    @property
    def ok(self) -> bool:
        return False
