import uuid

from backend.app.core.config import get_settings
from backend.app.core.database import get_database
from backend.app.schemas.chat import ChatResponse
from backend.app.schemas.common import Citation, RetrievedChunk
from backend.app.services.llm_client import LLMClient
from backend.app.services.vector_store import get_vector_store


class RagService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.db = get_database()
        self.vector_store = get_vector_store()
        self.llm = LLMClient(self.settings)

    def search(self, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
        return self.vector_store.search(query, top_k or self.settings.top_k)

    def chat(self, query: str, top_k: int | None = None) -> ChatResponse:
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        chunks = self.search(query, top_k)
        result = self.llm.answer_question(query, chunks)
        self.db.save_llm_log(
            log_id=f"log_{uuid.uuid4().hex[:12]}",
            request_id=request_id,
            model=result.model,
            prompt_version=self.settings.prompt_version,
            latency_ms=result.latency_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
            tool_calls=["search_policy_docs", "answer_question"],
            error=result.error,
        )
        return ChatResponse(
            answer=result.content,
            citations=[self._citation_from_chunk(chunk) for chunk in chunks],
            request_id=request_id,
        )

    def _citation_from_chunk(self, chunk: RetrievedChunk) -> Citation:
        return Citation(
            chunk_id=chunk.chunk_id,
            document_name=chunk.document_name,
            source_text=chunk.text[:500],
            similarity=chunk.similarity,
        )


def get_rag_service() -> RagService:
    return RagService()
