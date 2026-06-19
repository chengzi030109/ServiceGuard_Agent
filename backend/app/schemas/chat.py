from pydantic import BaseModel, Field

from backend.app.schemas.common import Citation


class ChatRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    request_id: str
