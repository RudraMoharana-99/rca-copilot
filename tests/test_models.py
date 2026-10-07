import pytest

from rca_copilot.models import (
    DiagnoseRequest,
    Evidence,
    Hypothesis,
    IncidentState,
    Verdict,
)


def test_hypothesis_without_evidence_is_rejected():
    with pytest.raises(ValueError):
        Hypothesis(
            agent="x",
            cause="y",
            confidence=0.5,
            evidence_ids=[],
        )


def test_unknown_evidence_reference_is_rejected():
    hypothesis = Hypothesis(
        agent="x",
        cause="y",
        confidence=0.5,
        evidence_ids=["missing"],
    )

    with pytest.raises(ValueError, match="missing"):
        IncidentState(
            incident_id="i1",
            alert={},
            window_start="2026-09-03T07:00:00Z",
            window_end="2026-09-03T08:00:00Z",
            hypotheses=[hypothesis],
        )


def test_valid_state_constructs():
    evidence = Evidence(
        agent="x",
        source="logs",
        query={},
        status="SUCCESS",
        summary="Found an error",
        timestamp="2026-09-03T07:30:00Z",
    )

    hypothesis = Hypothesis(
        agent="x",
        cause="The service failed.",
        confidence=0.5,
        evidence_ids=[evidence.evidence_id],
    )

    state = IncidentState(
        incident_id="i1",
        alert={},
        window_start="2026-09-03T07:00:00Z",
        window_end="2026-09-03T08:00:00Z",
        evidence=[evidence],
        hypotheses=[hypothesis],
    )

    assert state.hypotheses[0].evidence_ids == [evidence.evidence_id]


def test_degraded_verdict_allows_no_ranked_causes():
    verdict = Verdict(
        ranked_causes=[],
        overall_confidence=0.0,
        dissent=None,
        escalate=True,
        escalation_reason="LLM provider unavailable",
    )

    assert verdict.ranked_causes == []
    assert verdict.escalate is True


def test_non_escalated_verdict_requires_ranked_cause():
    with pytest.raises(
        ValueError,
        match="ranked_causes must contain at least one cause",
    ):
        Verdict(
            ranked_causes=[],
            overall_confidence=0.0,
            dissent=None,
            escalate=False,
            escalation_reason=None,
        )


def test_diagnose_request_accepts_normal_alert():
    request = DiagnoseRequest(
        scenario="C1-valkey-cart-down",
        alert={"message": "elevated cart error rate detected"},
        window_start="2026-09-03T06:59:19Z",
        window_end="2026-09-03T07:14:19Z",
        config="baseline",
    )

    assert request.alert["message"] == "elevated cart error rate detected"


def test_diagnose_request_rejects_oversized_alert():
    with pytest.raises(
        ValueError,
        match="alert must not exceed 16384 bytes",
    ):
        DiagnoseRequest(
            scenario="C1-valkey-cart-down",
            alert={"message": "X" * (1024 * 1024)},
            window_start="2026-09-03T06:59:19Z",
            window_end="2026-09-03T07:14:19Z",
            config="baseline",
        )
