from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.schemas import (
    AnalysisRequest,
    CohortDefinition,
    ConfounderTest,
    Evidence,
    RCAReport,
    RootCauseHypothesis,
    RunMetadata,
    RunStatus,
    TimeWindow,
)


def _cohort(instance_id: str = "inst_001") -> CohortDefinition:
    return CohortDefinition(
        instance_id=instance_id,
        os="iOS 17",
        required_events=["checkout_start"],
        description="iOS 17 users who reached checkout",
    )


def _hypothesis(confidence: float = 0.8) -> RootCauseHypothesis:
    return RootCauseHypothesis(
        hypothesis_id="hyp_001",
        rank=1,
        mechanism="Checkout latency increased after the incident began.",
        affected_cohort=_cohort(),
        resolved_events=["CheckoutStart", "begin_checkout"],
        evidence=[
            Evidence(
                evidence_id="ev_001",
                claim="Checkout p95 increased relative to baseline.",
                metric_name="checkout_latency_p95_ms",
                observed_value=4200,
                comparison_value=1300,
                sample_size=245,
                query_id="query_001",
                source_chunk_ids=["prd:slo:checkout"],
            )
        ],
        confounders=[
            ConfounderTest(
                confounder="device age",
                method="stratify checkout latency by device age",
                result="The regression remains within device-age strata.",
                status="ruled_out",
            )
        ],
        confidence=confidence,
        limitations=["The incident window contains seven days of data."],
    )


def test_analysis_request_and_time_window_validation() -> None:
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    request = AnalysisRequest(
        instance_id="inst_001",
        symptom="Checkout conversion declined.",
        incident_window=TimeWindow(start=start, end=start + timedelta(days=7)),
    )
    assert request.instance_id == "inst_001"

    with pytest.raises(ValidationError):
        TimeWindow(start=start, end=start)


def test_missing_instance_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AnalysisRequest(symptom="Checkout conversion declined.")

    with pytest.raises(ValidationError):
        CohortDefinition(description="All users")


def test_invalid_confidence_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _hypothesis(confidence=1.01)

    with pytest.raises(ValidationError):
        _hypothesis(confidence=-0.01)


def test_report_uses_shared_contract() -> None:
    start = datetime.now(timezone.utc)
    metadata = RunMetadata(
        run_id="run_001",
        system_name="system_c",
        instance_id="inst_001",
        start_time=start,
        completion_time=start + timedelta(seconds=2),
        status=RunStatus.COMPLETED,
    )
    report = RCAReport(
        instance_id="inst_001",
        symptom="Checkout conversion declined.",
        hypotheses=[_hypothesis()],
        run_metadata=metadata,
    )
    assert report.hypotheses[0].rank == 1
    assert report.run_metadata.system_name == "system_c"


def test_mutable_defaults_are_isolated() -> None:
    first_cohort = CohortDefinition(instance_id="inst_001", description="First")
    second_cohort = CohortDefinition(instance_id="inst_001", description="Second")
    first_cohort.required_events.append("checkout_start")
    assert second_cohort.required_events == []

    start = datetime.now(timezone.utc)
    metadata_one = RunMetadata(
        run_id="run_001", system_name="system_a", instance_id="inst_001", start_time=start
    )
    metadata_two = RunMetadata(
        run_id="run_002", system_name="system_b", instance_id="inst_001", start_time=start
    )
    first_report = RCAReport(
        instance_id="inst_001", symptom="First", run_metadata=metadata_one
    )
    second_report = RCAReport(
        instance_id="inst_001", symptom="Second", run_metadata=metadata_two
    )
    first_report.unresolved_questions.append("Need a longer incident window?")
    assert second_report.unresolved_questions == []


def test_report_rejects_mismatched_instance_id() -> None:
    with pytest.raises(ValidationError):
        RCAReport(
            instance_id="inst_001",
            symptom="Checkout conversion declined.",
            hypotheses=[_hypothesis()],
            run_metadata=RunMetadata(
                run_id="run_001", system_name="system_a", instance_id="inst_002"
            ),
        )
