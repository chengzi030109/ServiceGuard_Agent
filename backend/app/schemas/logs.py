from typing import Any, Literal

from pydantic import BaseModel, Field

ReviewStatus = Literal["not_required", "pending", "approved", "rejected", "escalated"]
ReviewDecision = Literal["approved", "rejected", "escalated", "pending"]


class LLMCallLog(BaseModel):
    id: str
    request_id: str
    model: str
    prompt_version: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    tool_calls: list[str]
    error: str | None
    created_at: str


class ReportRecord(BaseModel):
    id: str
    ticket_id: str
    raw_text: str
    review_status: ReviewStatus
    review_comment: str | None = None
    reviewed_by_hash: str | None = None
    reviewed_at: str | None = None
    created_at: str
    report: dict[str, Any]


class ReportReviewUpdate(BaseModel):
    review_status: ReviewDecision
    review_comment: str | None = Field(default=None, max_length=1000)


class RetentionPurgeRequest(BaseModel):
    data_older_than_days: int | None = Field(default=None, ge=1, le=3650)
    audit_older_than_days: int | None = Field(default=None, ge=1, le=3650)
    include_audit: bool = False
    dry_run: bool = True


class RetentionPurgeResponse(BaseModel):
    dry_run: bool
    include_audit: bool
    cutoff_by_table: dict[str, str]
    deleted_counts: dict[str, int]


class BackupCreateRequest(BaseModel):
    include_uploads: bool = True
    include_chroma: bool = False


class BackupSnapshot(BaseModel):
    id: str
    filename: str
    size_bytes: int
    created_at: str
    include_uploads: bool
    include_chroma: bool
    database_stats: dict[str, int] = Field(default_factory=dict)


class BackupVerification(BaseModel):
    id: str
    filename: str
    valid: bool
    checks: dict[str, bool]
    errors: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)
    manifest_signed: bool = False
    file_counts: dict[str, int] = Field(default_factory=dict)
    verified_files: int = 0
    sqlite_integrity_result: str | None = None


class BackupRestoreDryRun(BaseModel):
    id: str
    filename: str
    dry_run: bool
    restore_ready: bool
    checks: dict[str, bool]
    errors: list[str] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)
    sqlite_integrity_result: str | None = None
    missing_tables: list[str] = Field(default_factory=list)
    manifest_database_stats: dict[str, int] = Field(default_factory=dict)
    restored_database_stats: dict[str, int] = Field(default_factory=dict)


class AuditChainVerification(BaseModel):
    valid: bool
    total_events: int
    hashed_events: int
    legacy_events_without_hash: int
    tampered_events: int
    first_invalid_event_id: str | None = None
    last_event_hash: str | None = None


class SecurityStatus(BaseModel):
    status: str
    app_env: str
    production_mode: bool
    production_ready: bool
    warnings: list[str]
    controls: dict[str, Any]
    audit_chain: AuditChainVerification


class AuditEvent(BaseModel):
    id: str
    request_id: str
    actor_role: str
    actor_hash: str
    method: str
    path: str
    status_code: int
    latency_ms: int
    client_host: str | None
    previous_hash: str
    event_hash: str
    created_at: str
