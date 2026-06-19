from typing import Literal

from pydantic import BaseModel, Field

from backend.app.schemas.common import Citation

ViolationType = Literal[
    "over_promise",
    "process_missing",
    "privacy_risk",
    "attitude_issue",
    "policy_conflict",
    "unknown",
]
Severity = Literal["low", "medium", "high"]
RiskLevel = Literal["low", "medium", "high"]


class Violation(BaseModel):
    type: ViolationType
    severity: Severity
    evidence_from_ticket: str
    policy_citation_ids: list[str] = Field(default_factory=list)
    explanation: str
    fix_suggestion: str


class QualityReport(BaseModel):
    ticket_id: str
    score: int = Field(ge=0, le=100)
    risk_level: RiskLevel
    summary: str
    violations: list[Violation] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    suggested_reply: str
    need_human_review: bool
    confidence: float = Field(ge=0.0, le=1.0)
    missing_info: list[str] = Field(default_factory=list)


class TicketInspectRequest(BaseModel):
    ticket_text: str = Field(min_length=1)
    channel: str = "demo"
    top_k: int = Field(default=5, ge=1, le=20)


class TicketInspectResponse(BaseModel):
    report_id: str
    request_id: str
    report: QualityReport


class BatchTicketResult(BaseModel):
    row_number: int
    ticket_id: str
    ok: bool
    report_id: str | None = None
    report: QualityReport | None = None
    error: str | None = None


class BatchInspectResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[BatchTicketResult]


class BatchJobCreateResponse(BaseModel):
    job_id: str
    status: str
    idempotent_replay: bool = False


class BatchJobRecord(BaseModel):
    id: str
    status: str
    total: int
    succeeded: int
    failed: int
    result: BatchInspectResponse | None = None
    error: str | None = None
    created_at: str
    updated_at: str
