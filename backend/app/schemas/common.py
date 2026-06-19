from pydantic import BaseModel, Field


class Citation(BaseModel):
    chunk_id: str
    document_name: str
    source_text: str
    similarity: float = Field(ge=0.0, le=1.0)


class RetrievedChunk(BaseModel):
    chunk_id: str
    doc_id: str
    document_name: str
    text: str
    source: str
    page: int | None = None
    similarity: float = Field(ge=0.0, le=1.0)
