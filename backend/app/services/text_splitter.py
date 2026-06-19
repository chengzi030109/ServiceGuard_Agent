from dataclasses import dataclass

from backend.app.services.document_loader import DocumentText


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    text: str
    source: str
    page: int | None
    token_count: int


class TextSplitter:
    def __init__(self, chunk_size: int = 700, chunk_overlap: int = 120):
        if chunk_size < 100:
            raise ValueError("chunk_size must be at least 100")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be >= 0 and smaller than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, documents: list[DocumentText]) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        for doc in documents:
            for piece in self._split_text(doc.text):
                if piece.strip():
                    chunks.append(
                        TextChunk(
                            chunk_index=len(chunks),
                            text=piece.strip(),
                            source=doc.source,
                            page=doc.page,
                            token_count=self._rough_token_count(piece),
                        )
                    )
        return chunks

    def _split_text(self, text: str) -> list[str]:
        normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if len(normalized) <= self.chunk_size:
            return [normalized]

        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(start + self.chunk_size, len(normalized))
            if end < len(normalized):
                boundary = max(
                    normalized.rfind("\n", start, end),
                    normalized.rfind("。", start, end),
                    normalized.rfind(".", start, end),
                    normalized.rfind("；", start, end),
                    normalized.rfind(";", start, end),
                )
                if boundary > start + self.chunk_size // 2:
                    end = boundary + 1
            chunks.append(normalized[start:end])
            if end >= len(normalized):
                break
            start = max(0, end - self.chunk_overlap)
        return chunks

    def _rough_token_count(self, text: str) -> int:
        chinese_chars = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
        other_chars = len(text) - chinese_chars
        return chinese_chars + max(1, other_chars // 4)
