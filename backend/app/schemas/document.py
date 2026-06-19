from pydantic import BaseModel, Field

from backend.app.schemas.common import RetrievedChunk


class DocumentRecord(BaseModel):
    id: str
    filename: str
    file_type: str
    status: str
    created_at: str
    chunk_count: int
    path: str
    security_review_status: str = "approved"
    prompt_injection_detected: bool = False
    prompt_injection_risks: dict[str, int] = Field(default_factory=dict)


class DocumentUploadResponse(BaseModel):
    document: DocumentRecord
    chunks_indexed: int
    sensitive_redactions: dict[str, int] = Field(default_factory=dict)
    prompt_injection_detected: bool = False
    prompt_injection_risks: dict[str, int] = Field(default_factory=dict)


class DocumentReviewResponse(BaseModel):
    document: DocumentRecord
    chunks_indexed: int
    prompt_injection_detected: bool = False
    prompt_injection_risks: dict[str, int] = Field(default_factory=dict)


class DocumentPrivacyRemediationRequest(BaseModel):
    dry_run: bool = True


class DocumentPrivacyRemediationResponse(BaseModel):
    dry_run: bool
    scanned_documents: int
    scanned_chunks: int
    affected_documents: int
    affected_chunks: int
    affected_files: int
    remediated_chunks: int
    remediated_files: int
    missing_files: int
    skipped_files: int
    redaction_counts: dict[str, int] = Field(default_factory=dict)
    document_ids: list[str] = Field(default_factory=list)


class DocumentSecurityScanResponse(BaseModel):
    scanned_documents: int
    scanned_chunks: int
    affected_documents: int
    affected_chunks: int
    affected_files: int
    missing_files: int
    skipped_files: int
    prompt_injection_detected: bool = False
    prompt_injection_risks: dict[str, int] = Field(default_factory=dict)
    document_ids: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class SearchResponse(BaseModel):
    query: str
    results: list[RetrievedChunk]
