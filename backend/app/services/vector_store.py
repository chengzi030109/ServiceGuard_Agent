from functools import lru_cache
from typing import Any

import chromadb

from backend.app.core.config import get_settings
from backend.app.schemas.common import RetrievedChunk
from backend.app.services.embedding import OpenAIEmbeddingProvider


class ChromaVectorStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.embedder = OpenAIEmbeddingProvider(self.settings)
        self.client = chromadb.PersistentClient(path=str(self.settings.chroma_path))
        self.collection = self.client.get_or_create_collection(
            name="serviceguard_chunks",
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_chunks(self, chunks: list[dict[str, Any]]) -> None:
        if not chunks:
            return
        embeddings = self.embedder.embed_texts([chunk["text"] for chunk in chunks])
        self.collection.upsert(
            ids=[chunk["id"] for chunk in chunks],
            embeddings=embeddings,
            documents=[chunk["text"] for chunk in chunks],
            metadatas=[
                {
                    "doc_id": chunk["doc_id"],
                    "document_name": chunk["document_name"],
                    "source": chunk["source"],
                    "page": chunk.get("page") or 0,
                    "chunk_index": chunk["chunk_index"],
                }
                for chunk in chunks
            ],
        )

    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        embedding = self.embedder.embed_text(query)
        result = self.collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        chunks: list[RetrievedChunk] = []
        for chunk_id, text, metadata, distance in zip(ids, docs, metas, distances, strict=False):
            page = int(metadata.get("page") or 0) or None
            similarity = max(0.0, min(1.0, 1.0 - float(distance)))
            chunks.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    doc_id=str(metadata["doc_id"]),
                    document_name=str(metadata["document_name"]),
                    text=text,
                    source=str(metadata["source"]),
                    page=page,
                    similarity=similarity,
                )
            )
        return chunks

    def delete_by_doc_id(self, doc_id: str) -> None:
        self.collection.delete(where={"doc_id": doc_id})


@lru_cache
def get_vector_store() -> ChromaVectorStore:
    return ChromaVectorStore()
