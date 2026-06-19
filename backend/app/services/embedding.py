import hashlib
import math
import re
from collections.abc import Iterable

from openai import OpenAI

from backend.app.core.config import Settings


class EmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


class LocalHashEmbeddingProvider(EmbeddingProvider):
    """Deterministic local embeddings for tests and no-key demos."""

    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in self._tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            index = value % self.dimensions
            sign = 1.0 if value & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(item * item for item in vector)) or 1.0
        return [item / norm for item in vector]

    def _tokens(self, text: str) -> Iterable[str]:
        lowered = text.lower()
        tokens = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", lowered)
        if not tokens:
            tokens = list(lowered)
        return tokens


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.fallback = LocalHashEmbeddingProvider()
        self.client = (
            OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
            if settings.has_remote_llm
            else None
        )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self.settings.has_remote_llm:
            return self.fallback.embed_texts(texts)
        try:
            if self.client is None:
                return self.fallback.embed_texts(texts)
            response = self.client.embeddings.create(
                model=self.settings.embedding_model,
                input=texts,
            )
            return [item.embedding for item in response.data]
        except Exception:
            if self.settings.use_local_fallback:
                return self.fallback.embed_texts(texts)
            raise
