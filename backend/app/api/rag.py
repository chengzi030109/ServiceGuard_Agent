from fastapi import APIRouter, Depends

from backend.app.core.security import verify_api_key
from backend.app.schemas.chat import ChatRequest, ChatResponse
from backend.app.schemas.document import SearchRequest, SearchResponse
from backend.app.services.rag_service import get_rag_service

router = APIRouter(tags=["rag"], dependencies=[Depends(verify_api_key)])


@router.post("/api/search", response_model=SearchResponse)
@router.post("/search", response_model=SearchResponse, include_in_schema=False)
def search(request: SearchRequest) -> SearchResponse:
    results = get_rag_service().search(request.query, request.top_k)
    return SearchResponse(query=request.query, results=results)


@router.post("/api/chat", response_model=ChatResponse)
@router.post("/chat", response_model=ChatResponse, include_in_schema=False)
def chat(request: ChatRequest) -> ChatResponse:
    return get_rag_service().chat(request.query, request.top_k)
