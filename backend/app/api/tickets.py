from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile

from backend.app.core.config import get_settings
from backend.app.core.security import request_actor, verify_api_key
from backend.app.schemas.ticket import (
    BatchInspectResponse,
    BatchJobCreateResponse,
    BatchJobRecord,
    TicketInspectRequest,
    TicketInspectResponse,
)
from backend.app.services.ticket_service import (
    BatchJobCapacityExceeded,
    IdempotencyConflict,
    get_ticket_service,
)

router = APIRouter(tags=["tickets"], dependencies=[Depends(verify_api_key)])


@router.post("/api/tickets/inspect", response_model=TicketInspectResponse)
@router.post("/tickets/audit", response_model=TicketInspectResponse, include_in_schema=False)
def inspect_ticket(request: Request, payload: TicketInspectRequest) -> TicketInspectResponse:
    actor_role, actor_hash = request_actor(request)
    return get_ticket_service().inspect_ticket(
        payload.ticket_text,
        channel=payload.channel,
        top_k=payload.top_k,
        actor_role=actor_role,
        actor_hash=actor_hash,
    )


@router.post("/api/tickets/batch", response_model=BatchInspectResponse)
async def batch_inspect(
    request: Request,
    file: UploadFile = File(...),
    top_k: int = 5,
) -> BatchInspectResponse:
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")
    csv_bytes = await file.read()
    _enforce_csv_upload_size(csv_bytes)
    actor_role, actor_hash = request_actor(request)
    try:
        return get_ticket_service().batch_inspect_csv(
            csv_bytes,
            top_k=top_k,
            actor_role=actor_role,
            actor_hash=actor_hash,
        )
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/tickets/batch/jobs", response_model=BatchJobCreateResponse)
async def create_batch_job(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    top_k: int = 5,
) -> BatchJobCreateResponse:
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")
    csv_bytes = await file.read()
    _enforce_csv_upload_size(csv_bytes)
    service = get_ticket_service()
    actor_role, actor_hash = request_actor(request)
    try:
        job, created = service.create_or_reuse_batch_job(
            csv_bytes,
            top_k=top_k,
            actor_role=actor_role,
            actor_hash=actor_hash,
            idempotency_key=request.headers.get("idempotency-key"),
        )
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BatchJobCapacityExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": "30"},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if created:
        background_tasks.add_task(
            service.run_batch_job,
            job.id,
            csv_bytes,
            top_k,
            actor_role,
            actor_hash,
        )
    return BatchJobCreateResponse(
        job_id=job.id,
        status=job.status,
        idempotent_replay=not created,
    )


def _enforce_csv_upload_size(csv_bytes: bytes) -> None:
    settings = get_settings()
    if len(csv_bytes) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"CSV file is too large. Max upload size is {settings.max_upload_mb} MB",
        )


@router.get("/api/tickets/batch/jobs", response_model=list[BatchJobRecord])
def list_batch_jobs(request: Request, limit: int = 100) -> list[BatchJobRecord]:
    actor_role, actor_hash = request_actor(request)
    return get_ticket_service().list_batch_jobs(
        limit=limit,
        requester_role=actor_role,
        requester_hash=actor_hash,
    )


@router.get("/api/tickets/batch/jobs/{job_id}", response_model=BatchJobRecord)
def get_batch_job(request: Request, job_id: str) -> BatchJobRecord:
    actor_role, actor_hash = request_actor(request)
    job = get_ticket_service().get_batch_job(
        job_id,
        requester_role=actor_role,
        requester_hash=actor_hash,
    )
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")
    return job


@router.post("/api/tickets/batch/jobs/{job_id}/cancel", response_model=BatchJobRecord)
def cancel_batch_job(request: Request, job_id: str) -> BatchJobRecord:
    actor_role, actor_hash = request_actor(request)
    job = get_ticket_service().cancel_batch_job(
        job_id,
        requester_role=actor_role,
        requester_hash=actor_hash,
    )
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")
    return job
