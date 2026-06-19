from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from backend.app.core.config import get_settings
from backend.app.core.database import get_database
from backend.app.core.security import (
    can_view_owned_resource,
    request_actor,
    verify_admin_api_key,
    verify_api_key,
)
from backend.app.schemas.logs import (
    AuditAnchorSnapshot,
    AuditAnchorVerification,
    AuditChainVerification,
    AuditEvent,
    BackupCreateRequest,
    BackupRestoreDryRun,
    BackupSnapshot,
    BackupVerification,
    LLMCallLog,
    ReportRecord,
    ReportReviewUpdate,
    RetentionPurgeRequest,
    RetentionPurgeResponse,
    ReviewStatus,
    SecurityStatus,
)
from backend.app.services.audit_anchor_service import get_audit_anchor_service
from backend.app.services.backup_service import get_backup_service

router = APIRouter(tags=["logs"])


@router.get(
    "/api/logs",
    response_model=list[LLMCallLog],
    dependencies=[Depends(verify_admin_api_key)],
)
def list_logs(limit: int = 100, error_only: bool = False) -> list[LLMCallLog]:
    return [
        LLMCallLog(**item) for item in get_database().list_logs(limit=limit, error_only=error_only)
    ]


@router.get(
    "/api/audit-events",
    response_model=list[AuditEvent],
    dependencies=[Depends(verify_admin_api_key)],
)
def list_audit_events(limit: int = 100) -> list[AuditEvent]:
    return [AuditEvent(**item) for item in get_database().list_audit_events(limit=limit)]


@router.get(
    "/api/admin/security/status",
    response_model=SecurityStatus,
    dependencies=[Depends(verify_admin_api_key)],
)
def security_status(request: Request) -> SecurityStatus:
    settings = get_settings()
    database = get_database()
    audit_chain = AuditChainVerification(**database.verify_audit_chain())
    schema_status = database.schema_status()
    sqlite_status = database.sqlite_runtime_status()
    warnings = settings.production_config_errors()
    if not settings.is_production:
        warnings = [
            "APP_ENV is not production; development defaults may be unsafe for production",
            *warnings,
        ]
    if not audit_chain.valid:
        warnings.append("Audit event hash chain verification failed")
    if schema_status["status"] != "up_to_date":
        warnings.append("Database schema migrations are pending")
    if not sqlite_status["quick_check_ok"]:
        warnings.append("SQLite quick_check failed")

    controls = {
        "api_key_required": settings.require_api_key,
        "user_api_keys_configured": settings.has_user_api_key_material,
        "admin_api_keys_configured": settings.has_admin_api_key_material,
        "user_plaintext_api_keys_configured": bool(settings.parsed_api_keys),
        "admin_plaintext_api_keys_configured": bool(settings.parsed_admin_api_keys),
        "user_api_key_hashes_configured": bool(settings.parsed_api_key_hashes),
        "admin_api_key_hashes_configured": bool(settings.parsed_admin_api_key_hashes),
        "trusted_proxy_auth_enabled": settings.trusted_proxy_auth_enabled,
        "trusted_proxy_auth_secret_configured": bool(settings.trusted_proxy_auth_secret.strip()),
        "trusted_proxy_user_header": settings.trusted_proxy_user_header,
        "trusted_proxy_role_header": settings.trusted_proxy_role_header,
        "trusted_proxy_secret_header": settings.trusted_proxy_secret_header,
        "cors_restricted": "*" not in settings.parsed_allowed_origins,
        "allowed_origins": settings.parsed_allowed_origins,
        "rate_limit_enabled": settings.rate_limit_enabled,
        "rate_limit_per_minute": settings.rate_limit_per_minute,
        "remote_llm_configured": settings.has_remote_llm,
        "local_fallback_enabled": settings.use_local_fallback,
        "max_upload_mb": settings.max_upload_mb,
        "max_batch_rows": settings.max_batch_rows,
        "batch_job_timeout_seconds": settings.batch_job_timeout_seconds,
        "max_active_batch_jobs": settings.max_active_batch_jobs,
        "max_active_batch_jobs_per_actor": settings.max_active_batch_jobs_per_actor,
        "active_batch_jobs": database.active_batch_job_count(),
        "data_retention_days": settings.data_retention_days,
        "audit_retention_days": settings.audit_retention_days,
        "backup_signing_configured": bool(settings.backup_signing_key.strip()),
        "sqlite_journal_mode": sqlite_status["journal_mode"],
        "sqlite_synchronous": sqlite_status["synchronous"],
        "sqlite_busy_timeout_ms": sqlite_status["busy_timeout_ms"],
        "sqlite_foreign_keys_enabled": sqlite_status["foreign_keys_enabled"],
        "sqlite_quick_check_ok": sqlite_status["quick_check_ok"],
        "interrupted_batch_jobs_on_startup": getattr(
            request.app.state,
            "interrupted_batch_jobs_on_startup",
            0,
        ),
        "audit_chain_valid": audit_chain.valid,
        "audit_chain_hashed_events": audit_chain.hashed_events,
        "audit_chain_legacy_events_without_hash": audit_chain.legacy_events_without_hash,
        "database_schema_status": schema_status["status"],
        "database_schema_current_version": schema_status["current_version"],
        "database_schema_expected_version": schema_status["expected_version"],
        "database_schema_pending_versions": schema_status["pending_versions"],
    }
    production_ready = settings.is_production and not warnings
    return SecurityStatus(
        status="ready" if production_ready else "warning",
        app_env=settings.app_env,
        production_mode=settings.is_production,
        production_ready=production_ready,
        warnings=warnings,
        controls=controls,
        audit_chain=audit_chain,
    )


@router.get(
    "/api/audit-events/verify",
    response_model=AuditChainVerification,
    dependencies=[Depends(verify_admin_api_key)],
)
def verify_audit_events() -> AuditChainVerification:
    return AuditChainVerification(**get_database().verify_audit_chain())


@router.post(
    "/api/admin/audit-anchors",
    response_model=AuditAnchorSnapshot,
    dependencies=[Depends(verify_admin_api_key)],
)
def create_audit_anchor(request: Request) -> AuditAnchorSnapshot:
    actor_role, actor_hash = request_actor(request)
    snapshot = get_audit_anchor_service().create_anchor(
        actor_role=actor_role,
        actor_hash=actor_hash,
    )
    return AuditAnchorSnapshot(**snapshot)


@router.get(
    "/api/admin/audit-anchors",
    response_model=list[AuditAnchorSnapshot],
    dependencies=[Depends(verify_admin_api_key)],
)
def list_audit_anchors() -> list[AuditAnchorSnapshot]:
    return [AuditAnchorSnapshot(**item) for item in get_audit_anchor_service().list_anchors()]


@router.get(
    "/api/admin/audit-anchors/{anchor_id}/verify",
    response_model=AuditAnchorVerification,
    dependencies=[Depends(verify_admin_api_key)],
)
def verify_audit_anchor(anchor_id: str) -> AuditAnchorVerification:
    verification = get_audit_anchor_service().verify_anchor(anchor_id)
    if not verification:
        raise HTTPException(status_code=404, detail="Audit anchor not found")
    return AuditAnchorVerification(**verification)


@router.post(
    "/api/admin/retention/purge",
    response_model=RetentionPurgeResponse,
    dependencies=[Depends(verify_admin_api_key)],
)
def purge_retained_data(payload: RetentionPurgeRequest) -> RetentionPurgeResponse:
    settings = get_settings()
    data_days = payload.data_older_than_days or settings.data_retention_days
    audit_days = payload.audit_older_than_days or settings.audit_retention_days
    data_cutoff = _retention_cutoff(data_days)

    cutoff_by_table = {
        "reports": data_cutoff,
        "llm_call_logs": data_cutoff,
        "batch_jobs": data_cutoff,
        "idempotency_records": data_cutoff,
    }
    if payload.include_audit:
        cutoff_by_table["audit_events"] = _retention_cutoff(audit_days)

    deleted_counts = get_database().purge_operational_data(
        cutoff_by_table=cutoff_by_table,
        dry_run=payload.dry_run,
    )
    return RetentionPurgeResponse(
        dry_run=payload.dry_run,
        include_audit=payload.include_audit,
        cutoff_by_table=cutoff_by_table,
        deleted_counts=deleted_counts,
    )


@router.post(
    "/api/admin/backups",
    response_model=BackupSnapshot,
    dependencies=[Depends(verify_admin_api_key)],
)
def create_backup(payload: BackupCreateRequest) -> BackupSnapshot:
    return BackupSnapshot(**get_backup_service().create_backup(**payload.model_dump()))


@router.get(
    "/api/admin/backups",
    response_model=list[BackupSnapshot],
    dependencies=[Depends(verify_admin_api_key)],
)
def list_backups() -> list[BackupSnapshot]:
    return [BackupSnapshot(**item) for item in get_backup_service().list_backups()]


@router.get(
    "/api/admin/backups/{backup_id}/verify",
    response_model=BackupVerification,
    dependencies=[Depends(verify_admin_api_key)],
)
def verify_backup(backup_id: str) -> BackupVerification:
    verification = get_backup_service().verify_backup(backup_id)
    if not verification:
        raise HTTPException(status_code=404, detail="Backup not found")
    return BackupVerification(**verification)


@router.post(
    "/api/admin/backups/{backup_id}/restore/dry-run",
    response_model=BackupRestoreDryRun,
    dependencies=[Depends(verify_admin_api_key)],
)
def restore_backup_dry_run(backup_id: str) -> BackupRestoreDryRun:
    result = get_backup_service().restore_backup_dry_run(backup_id)
    if not result:
        raise HTTPException(status_code=404, detail="Backup not found")
    return BackupRestoreDryRun(**result)


@router.get(
    "/api/admin/backups/{backup_id}/download",
    dependencies=[Depends(verify_admin_api_key)],
)
def download_backup(backup_id: str) -> FileResponse:
    backup_path = get_backup_service().resolve_backup_path(backup_id)
    if not backup_path:
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(
        backup_path,
        media_type="application/zip",
        filename=backup_path.name,
    )


@router.get(
    "/api/reports",
    response_model=list[ReportRecord],
    dependencies=[Depends(verify_api_key)],
)
def list_reports(
    request: Request,
    limit: int = 100,
    review_status: ReviewStatus | None = None,
) -> list[ReportRecord]:
    requester_role, requester_hash = request_actor(request)
    actor_hash = (
        None
        if can_view_owned_resource(requester_role, requester_hash, owner_hash="__global__")
        else requester_hash
    )
    return [
        ReportRecord(**item)
        for item in get_database().list_reports(
            limit=limit,
            actor_hash=actor_hash,
            review_status=review_status,
        )
    ]


@router.get(
    "/api/reports/{report_id}",
    response_model=ReportRecord,
    dependencies=[Depends(verify_api_key)],
)
def get_report(request: Request, report_id: str) -> ReportRecord:
    report = get_database().get_report(report_id)
    requester_role, requester_hash = request_actor(request)
    if not report or not can_view_owned_resource(
        requester_role,
        requester_hash,
        owner_hash=report.get("actor_hash", "unknown"),
    ):
        raise HTTPException(status_code=404, detail="Report not found")
    return ReportRecord(**report)


@router.patch(
    "/api/reports/{report_id}/review",
    response_model=ReportRecord,
    dependencies=[Depends(verify_admin_api_key)],
)
def update_report_review(
    request: Request,
    report_id: str,
    payload: ReportReviewUpdate,
) -> ReportRecord:
    report = get_database().get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    _, reviewer_hash = request_actor(request)
    updated = get_database().update_report_review(
        report_id,
        review_status=payload.review_status,
        review_comment=payload.review_comment,
        reviewed_by_hash=reviewer_hash,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Report not found")
    return ReportRecord(**updated)


def _retention_cutoff(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()
