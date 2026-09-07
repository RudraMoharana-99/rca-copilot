from eval.scoring import score_verdict
from rca_copilot.models import RankedCause, Verdict


def make_cause(
    cause: str,
    confidence: float,
) -> RankedCause:
    return RankedCause(
        cause=cause,
        confidence=confidence,
        evidence_ids=["e1"],
    )


def test_correct_when_expected_component_is_first():
    verdict = Verdict(
        ranked_causes=[
            make_cause(
                "valkey-cart became unavailable",
                0.90,
            ),
            make_cause(
                "checkout experienced high latency",
                0.60,
            ),
        ],
        overall_confidence=0.85,
        dissent="Checkout was considered but ranked lower.",
        escalate=False,
    )

    result = score_verdict(
        verdict,
        expected_component="valkey-cart",
    )

    assert result["correct"] is True
    assert result["rank_position"] == 1
    assert result["top_confidence"] == 0.90
    assert result["overall_confidence"] == 0.85
    assert result["escalated"] is False
    assert result["num_causes"] == 2


def test_wrong_when_expected_component_is_second():
    verdict = Verdict(
        ranked_causes=[
            make_cause(
                "DNS resolution failure",
                0.80,
            ),
            make_cause(
                "Valkey cart became unavailable",
                0.70,
            ),
        ],
        overall_confidence=0.75,
        dissent="Valkey cart was considered as an alternative.",
        escalate=False,
    )

    result = score_verdict(
        verdict,
        expected_component="valkey-cart",
    )

    assert result["correct"] is False
    assert result["rank_position"] == 2
    assert result["top_confidence"] == 0.80
    assert result["num_causes"] == 2


def test_expected_component_absent():
    verdict = Verdict(
        ranked_causes=[
            make_cause(
                "DNS resolution failure",
                0.80,
            ),
            make_cause(
                "checkout memory pressure",
                0.60,
            ),
        ],
        overall_confidence=0.70,
        dissent="Other causes were considered.",
        escalate=False,
    )

    result = score_verdict(
        verdict,
        expected_component="valkey-cart",
    )

    assert result["correct"] is False
    assert result["rank_position"] is None
    assert result["top_confidence"] == 0.80
    assert result["num_causes"] == 2


def test_no_verdict():
    result = score_verdict(
        verdict=None,
        expected_component="valkey-cart",
    )

    assert result["correct"] is False
    assert result["rank_position"] is None
    assert result["top_confidence"] is None
    assert result["overall_confidence"] is None
    assert result["escalated"] is None
    assert result["num_causes"] == 0
