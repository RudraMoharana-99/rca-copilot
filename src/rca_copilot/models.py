from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from .sources.base import Status


class Evidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: uuid4().hex[:8])
    agent: str
    source: str
    query: dict
    status: Status
    summary: str
    raw: dict | None = None
    timestamp: datetime


class Hypothesis(BaseModel):
    hypothesis_id: str = Field(default_factory=lambda: uuid4().hex[:8])
    agent: str
    cause: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(min_length=1)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)


class Verdict(BaseModel):
    ranked_causes: list[Hypothesis]
    overall_confidence: float
    dissent: str | None = None
    escalate: bool
    escalation_reason: str | None = None


class IncidentState(BaseModel):
    incident_id: str
    alert: dict
    window_start: datetime
    window_end: datetime

    evidence: list[Evidence] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)

    verdict: Verdict | None = None

    run_meta: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_evidence_references(self):
        evidence_ids = {e.evidence_id for e in self.evidence}

        for hypothesis in self.hypotheses:
            for evidence_id in hypothesis.evidence_ids:
                if evidence_id not in evidence_ids:
                    raise ValueError(
                        f"Hypothesis {hypothesis.hypothesis_id} "
                        f"reference unknown evidence ID: {evidence_id}"
                    )

        return self
