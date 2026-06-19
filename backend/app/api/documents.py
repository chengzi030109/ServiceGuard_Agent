import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from backend.app.core.config import get_settings
from backend.app.core.security import verify_admin_api_key, verify_api_key
from backend.app.schemas.document import (
    DocumentPrivacyRemediationRequest,
    DocumentPrivacyRemediationResponse,
    DocumentRecord,
    DocumentReviewResponse,
    DocumentSecurityScanResponse,
    DocumentUploadResponse,
)
from backend.app.services.document_loader import DocumentLoaderError
from backend.app.services.document_service import get_document_service

router = APIRouter(tags=["documents"], dependencies=[Depends(verify_api_key)])


@router.post("/api/documents/upload", response_model=DocumentUploadResponse)
@router.post("/documents/upload", response_model=DocumentUploadResponse, include_in_schema=False)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    _: None = Depends(verify_admin_api_key),
) -> DocumentUploadResponse:
    settings = get_settings()
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File is too large. Max upload size is {settings.max_upload_mb} MB",
        )

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".txt", ".md", ".markdown", ".pdf"}:
        raise HTTPException(
            status_code=400,
            detail="Only TXT, Markdown, and PDF files are supported",
        )

    tmp_path: Path | None = None
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        content = await file.read()
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File is too large. Max upload size is {settings.max_upload_mb} MB",
            )
        tmp.write(content)
    try:
        (
            document,
            chunk_count,
            sensitive_redactions,
            prompt_injection_risks,
        ) = get_document_service().ingest_upload(
            file.filename or "upload",
            tmp_path,
        )
        return DocumentUploadResponse(
            document=document,
            chunks_indexed=chunk_count,
            sensitive_redactions=sensitive_redactions,
            prompt_injection_detected=bool(prompt_injection_risks),
            prompt_injection_risks=prompt_injection_risks,
        )
    except DocumentLoaderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


@router.get("/api/documents", response_model=list[DocumentRecord])
@router.get("/documents", response_model=list[DocumentRecord], include_in_schema=False)
def list_documents() -> list[DocumentRecord]:
    return get_document_service().list_documents()


@router.post(
    "/api/admin/documents/{doc_id}/approve",
    response_model=DocumentReviewResponse,
)
def approve_document(
    doc_id: str,
    _: None = Depends(verify_admin_api_key),
) -> DocumentReviewResponse:
    try:
        result = get_document_service().approve_document(doc_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Stored document file not found") from exc
    except DocumentLoaderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not result:
        raise HTTPException(status_code=404, detail="Document not found")
    document, chunk_count = result
    return DocumentReviewResponse(
        document=document,
        chunks_indexed=chunk_count,
        prompt_injection_detected=document.prompt_injection_detected,
        prompt_injection_risks=document.prompt_injection_risks,
    )


@router.post(
    "/api/admin/documents/{doc_id}/reject",
    response_model=DocumentReviewResponse,
)
def reject_document(
    doc_id: str,
    _: None = Depends(verify_admin_api_key),
) -> DocumentReviewResponse:
    document = get_document_service().reject_document(doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentReviewResponse(
        document=document,
        chunks_indexed=0,
        prompt_injection_detected=document.prompt_injection_detected,
        prompt_injection_risks=document.prompt_injection_risks,
    )


@router.post(
    "/api/admin/documents/privacy/remediate",
    response_model=DocumentPrivacyRemediationResponse,
)
def remediate_document_privacy(
    payload: DocumentPrivacyRemediationRequest,
    _: None = Depends(verify_admin_api_key),
) -> DocumentPrivacyRemediationResponse:
    return DocumentPrivacyRemediationResponse(
        **get_document_service().remediate_sensitive_data(dry_run=payload.dry_run)
    )


@router.get(
    "/api/admin/documents/security/scan",
    response_model=DocumentSecurityScanResponse,
)
def scan_document_security(
    _: None = Depends(verify_admin_api_key),
) -> DocumentSecurityScanResponse:
    return DocumentSecurityScanResponse(**get_document_service().scan_prompt_injection_risks())


@router.delete("/api/documents/{doc_id}")
def delete_document(
    doc_id: str,
    _: None = Depends(verify_admin_api_key),
) -> dict[str, bool]:
    deleted = get_document_service().delete_document(doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": True}


@router.get("/api/debug/chunks")
@router.get("/debug/chunks", include_in_schema=False)
def debug_chunks(
    limit: int = 100,
    _: None = Depends(verify_admin_api_key),
) -> list[dict]:
    return get_document_service().debug_chunks(limit=limit)
