import pytest

from rca_copilot.models import (
    Evidence,
    Hypothesis,
    IncidentState,
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
