from rca_copilot.models import Verdict


def _normalize_component(text: str) -> str:
    return text.lower().replace("-", " ").replace("_", " ")


def score_verdict(
    verdict: Verdict | None,
    expected_component: str,
) -> dict:
    if verdict is None:
        return {
            "correct": False,
            "rank_position": None,
            "top_confidence": None,
            "overall_confidence": None,
            "escalated": None,
            "num_causes": 0,
        }

    expected = _normalize_component(expected_component)

    rank_position = None

    for index, ranked_cause in enumerate(
        verdict.ranked_causes,
        start=1,
    ):
        cause_text = _normalize_component(ranked_cause.cause)

        if expected in cause_text:
            rank_position = index
            break

    top_confidence = verdict.ranked_causes[0].confidence if verdict.ranked_causes else None

    return {
        "correct": rank_position == 1,
        "rank_position": rank_position,
        "top_confidence": top_confidence,
        "overall_confidence": verdict.overall_confidence,
        "escalated": verdict.escalate,
        "num_causes": len(verdict.ranked_causes),
    }
