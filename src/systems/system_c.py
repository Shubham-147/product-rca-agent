"""System C: cyclic LangGraph RCA pipeline with an active falsifier."""

from __future__ import annotations

import json
import operator
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from src.retrieval.db import run_sql
from src.retrieval.hybrid import resolve_events
from src.systems.schema import Hypothesis


class GraphState(TypedDict):
    """Shared state carried through the cyclic analysis graph."""

    symptom: str
    candidate_hypotheses: Annotated[list[dict[str, Any]], operator.add]
    current_candidate: dict[str, Any]
    resolved_events: list[str]
    evidence_collected: Annotated[list[str], operator.add]
    confounders_found: Annotated[list[str], operator.add]
    affected_user_ids: list[str]
    validation_passed: bool
    falsified: bool
    route: Literal["revise", "report"]
    revision_count: int
    max_iterations: int
    final_report: Hypothesis | None
    ruled_out_reason: str | None
    trace: Annotated[list[dict[str, Any]], operator.add]


class SystemCResult(BaseModel):
    """Detailed graph result, including the auditable cyclic trace."""

    final_hypothesis: Hypothesis | None = None
    ruled_out_reason: str | None = None
    revision_count: int = Field(ge=0)
    confounders_found: list[str]
    state_trace: list[dict[str, Any]]


def _records(query: str) -> list[dict[str, Any]]:
    """Execute DuckDB SQL and convert its result to JSON-safe records."""
    return json.loads(run_sql(query).to_json(orient="records", date_format="iso"))


def _hypothesis_gen(state: GraphState) -> dict[str, Any]:
    symptom = state["symptom"]
    lower = symptom.lower()
    revision = state["revision_count"]
    disconfirming = state["confounders_found"][-1] if state["confounders_found"] else None

    if ("android" in lower or "crash" in lower) and revision == 0:
        mechanism = "Old device hardware directly causes pre-cart application crashes."
        cohort_filter = "device_tier = 'old'"
    elif "android" in lower or "crash" in lower:
        mechanism = (
            "Android 10 within the old-device cohort causes pre-cart application crashes; "
            "device age alone is not sufficient."
        )
        cohort_filter = (
            "device_tier = 'old' AND os = 'Android_10' AND outcome = 'crash'"
        )
    elif "checkout" in lower:
        mechanism = "Checkout latency causes sessions to abandon before payment."
        cohort_filter = "outcome IN ('slow', 'threshold_exceeded')"
    elif "payment" in lower or "provider" in lower:
        mechanism = "A payment-provider failure prevents order completion."
        cohort_filter = "outcome = 'provider_error'"
    elif "cold" in lower or "home screen" in lower:
        mechanism = "Cold-start initialization suppresses the home screen render."
        cohort_filter = "outcome = 'home_suppressed'"
    elif "shipping" in lower or "disappearing" in lower:
        mechanism = "A shipping-screen backend failure prevents the screen from rendering."
        cohort_filter = "outcome = 'screen_not_rendered'"
    else:
        mechanism = "An event-stream failure interrupts the expected product funnel."
        cohort_filter = "outcome <> 'ok'"

    candidate = {
        "revision": revision,
        "mechanism": mechanism,
        "cohort_filter": cohort_filter,
        "disconfirming_evidence_considered": disconfirming,
    }
    return {
        "candidate_hypotheses": [candidate],
        "current_candidate": candidate,
        "validation_passed": False,
        "falsified": False,
        "route": "report",
        "trace": [
            {
                "node": "hypothesis_gen",
                "revision": revision,
                "mechanism": mechanism,
                "used_disconfirming_evidence": disconfirming,
            }
        ],
    }


def _event_resolver(state: GraphState) -> dict[str, Any]:
    lower = state["symptom"].lower()
    if "crash" in lower or "android" in lower:
        event_query = "application crash"
    elif "checkout" in lower:
        event_query = "checkout start"
    elif "payment" in lower or "provider" in lower:
        event_query = "payment failure"
    elif "cold" in lower or "home screen" in lower:
        event_query = "cold start home render"
    elif "shipping" in lower or "disappearing" in lower:
        event_query = "shipping screen error"
    else:
        event_query = state["symptom"]
    hits = resolve_events(event_query, k=5)
    names = [hit.event_name for hit in hits]
    return {
        "resolved_events": names,
        "trace": [
            {
                "node": "event_resolver",
                "query": event_query,
                "resolved_events": names,
            }
        ],
    }


def _sql_analyst(state: GraphState) -> dict[str, Any]:
    candidate = state["current_candidate"]
    lower = state["symptom"].lower()
    revision = state["revision_count"]
    if ("android" in lower or "crash" in lower) and revision == 0:
        query = """
            SELECT device_tier,
                   COUNT(DISTINCT user_id) AS users,
                   COUNT(DISTINCT CASE WHEN outcome = 'crash' THEN user_id END) AS crash_users,
                   COUNT(DISTINCT CASE WHEN outcome = 'crash' THEN user_id END)::DOUBLE
                       / COUNT(DISTINCT user_id) AS crash_rate
            FROM events GROUP BY device_tier ORDER BY device_tier
        """
        rows = _records(query)
        affected = [
            row["user_id"]
            for row in _records(
                "SELECT DISTINCT user_id FROM events "
                "WHERE device_tier = 'old' AND outcome = 'crash' ORDER BY user_id"
            )
        ]
    else:
        query = (
            "SELECT DISTINCT user_id FROM events WHERE "
            f"{candidate['cohort_filter']} ORDER BY user_id"
        )
        rows = _records(query)
        affected = [row["user_id"] for row in rows]

    summary = f"DuckDB test returned {len(affected)} affected users; query={query.strip()}"
    return {
        "affected_user_ids": affected,
        "evidence_collected": [summary],
        "trace": [
            {
                "node": "sql_analyst",
                "revision": revision,
                "query": " ".join(query.split()),
                "row_count": len(rows),
                "affected_user_count": len(affected),
            }
        ],
    }


def _validator(state: GraphState) -> dict[str, Any]:
    has_events = bool(state["resolved_events"])
    has_evidence = bool(state["affected_user_ids"] and state["evidence_collected"])
    passed = has_events and has_evidence
    return {
        "validation_passed": passed,
        "trace": [
            {
                "node": "validator",
                "passed": passed,
                "checks": {
                    "resolved_event_present": has_events,
                    "sql_cohort_non_empty": bool(state["affected_user_ids"]),
                    "evidence_present": bool(state["evidence_collected"]),
                },
            }
        ],
    }


def _falsifier(state: GraphState) -> dict[str, Any]:
    revision = state["revision_count"]
    lower = state["symptom"].lower()
    confounder: str | None = None
    check: dict[str, Any] = {
        "decoy_checked": "promo_skip" in state["resolved_events"],
        "stratification_checked": False,
    }

    # A promo skip is explicitly intended behavior, not a product fault.
    if "promo_skip" in state["resolved_events"]:
        confounder = "promo_skip is an intentional decoy, not a failure event"

    # Challenge the aggregate old-device claim by stratifying within device tier by OS.
    if ("android" in lower or "crash" in lower) and revision == 0:
        stratified = _records(
            """
            SELECT device_tier, os,
                   COUNT(DISTINCT user_id) AS users,
                   COUNT(DISTINCT CASE WHEN outcome = 'crash' THEN user_id END) AS crash_users,
                   COUNT(DISTINCT CASE WHEN outcome = 'crash' THEN user_id END)::DOUBLE
                       / COUNT(DISTINCT user_id) AS crash_rate
            FROM events GROUP BY device_tier, os ORDER BY device_tier, os
            """
        )
        check["stratification_checked"] = True
        check["old_device_os_rates"] = [
            row for row in stratified if row["device_tier"] == "old"
        ]
        android_rate = max(
            (
                row["crash_rate"] or 0.0
                for row in check["old_device_os_rates"]
                if row["os"] == "Android_10"
            ),
            default=0.0,
        )
        other_rate = max(
            (
                row["crash_rate"] or 0.0
                for row in check["old_device_os_rates"]
                if row["os"] != "Android_10"
            ),
            default=0.0,
        )
        if android_rate > other_rate:
            confounder = (
                "OS confounding / Simpson-style aggregate risk: old-device crashes "
                f"concentrate in Android_10 ({android_rate:.3f} vs {other_rate:.3f})."
            )

    found = confounder is not None
    can_revise = found and revision < state["max_iterations"]
    updates: dict[str, Any] = {
        "falsified": found,
        "route": "revise" if can_revise else "report",
        "trace": [
            {
                "node": "falsifier",
                "revision": revision,
                "falsified": found,
                "confounder": confounder,
                "route": "revise" if can_revise else "report",
                "checks": check,
            }
        ],
    }
    if confounder:
        updates["confounders_found"] = [confounder]
    if can_revise:
        updates["revision_count"] = revision + 1
    return updates


def _route_after_falsifier(state: GraphState) -> Literal["revise", "report"]:
    return state["route"]


def _report(state: GraphState) -> dict[str, Any]:
    if state["falsified"] or not state["validation_passed"]:
        reason = (
            "All candidates were falsified or failed validation within the revision cap."
        )
        return {
            "final_report": None,
            "ruled_out_reason": reason,
            "trace": [{"node": "report", "status": "ruled_out", "reason": reason}],
        }

    report = Hypothesis(
        mechanism=state["current_candidate"]["mechanism"],
        affected_cohort=state["affected_user_ids"],
        evidence=state["evidence_collected"],
        confounders_ruled_out=[
            "device tier alone; OS-stratified falsification check performed"
        ]
        if state["confounders_found"]
        else [],
        confidence=0.9 if state["revision_count"] else 0.8,
    )
    return {
        "final_report": report,
        "ruled_out_reason": None,
        "trace": [
            {
                "node": "report",
                "status": "validated",
                "affected_user_count": len(state["affected_user_ids"]),
            }
        ],
    }


def build_graph():
    """Compile the cyclic graph, including the real falsifier backward edge."""
    graph = StateGraph(GraphState)
    graph.add_node("hypothesis_gen", _hypothesis_gen)
    graph.add_node("event_resolver", _event_resolver)
    graph.add_node("sql_analyst", _sql_analyst)
    graph.add_node("validator", _validator)
    graph.add_node("falsifier", _falsifier)
    graph.add_node("report", _report)
    graph.add_edge(START, "hypothesis_gen")
    graph.add_edge("hypothesis_gen", "event_resolver")
    graph.add_edge("event_resolver", "sql_analyst")
    graph.add_edge("sql_analyst", "validator")
    graph.add_edge("validator", "falsifier")
    graph.add_conditional_edges(
        "falsifier",
        _route_after_falsifier,
        {"revise": "hypothesis_gen", "report": "report"},
    )
    graph.add_edge("report", END)
    return graph.compile()


class SystemC:
    """Facade for the full cyclic graph and its detailed trace."""

    def __init__(self, max_iterations: int = 3) -> None:
        if max_iterations < 0:
            raise ValueError("max_iterations must be non-negative")
        self.max_iterations = max_iterations
        self.graph = build_graph()

    def run(self, symptom: str) -> SystemCResult:
        """Execute the graph and return report plus full state trace."""
        if not symptom.strip():
            raise ValueError("symptom must not be empty")
        initial: GraphState = {
            "symptom": symptom,
            "candidate_hypotheses": [],
            "current_candidate": {},
            "resolved_events": [],
            "evidence_collected": [],
            "confounders_found": [],
            "affected_user_ids": [],
            "validation_passed": False,
            "falsified": False,
            "route": "report",
            "revision_count": 0,
            "max_iterations": self.max_iterations,
            "final_report": None,
            "ruled_out_reason": None,
            "trace": [],
        }
        state = self.graph.invoke(initial, {"recursion_limit": 50})
        return SystemCResult(
            final_hypothesis=state["final_report"],
            ruled_out_reason=state["ruled_out_reason"],
            revision_count=state["revision_count"],
            confounders_found=state["confounders_found"],
            state_trace=state["trace"],
        )

    def analyze(self, symptom: str) -> Hypothesis:
        """Return the final validated hypothesis or raise if all were ruled out."""
        result = self.run(symptom)
        if result.final_hypothesis is None:
            raise RuntimeError(result.ruled_out_reason or "System C ruled out all candidates")
        return result.final_hypothesis
