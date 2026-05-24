"""Embedding service backed by Voyage AI.

Replaces the previous sentence-transformers / cross-encoder local stack. The
hosted approach removes ~3 GB of torch + model weights from the container
image and gives us higher-quality multilingual embeddings (relevant given
KLAS lecture materials are mostly Korean).

We keep the same `embed()` API as the old service so call sites in
`rag_service.py` are unaffected.
"""
from __future__ import annotations

import logging

import voyageai

from app.core.config import settings

logger = logging.getLogger(__name__)

# voyage-3 returns 1024-dim embeddings, supports 32 languages including Korean.
# voyage-3-lite (512-dim) is cheaper but lower quality; pick voyage-3 for now.
EMBEDDING_MODEL = "voyage-3"
EMBEDDING_DIM = 1024


class EmbeddingService:
    _instance: EmbeddingService | None = None
    _client: voyageai.Client | None = None

    @classmethod
    def get(cls) -> EmbeddingService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _client_(self) -> voyageai.Client:
        if self._client is None:
            self._client = voyageai.Client(api_key=settings.VOYAGE_API_KEY)
        return self._client

    def embed(self, texts: list[str], *, input_type: str = "document") -> list[list[float]]:
        """Embed a batch of texts.

        `input_type` is "document" for stored chunks and "query" for the
        question at retrieval time — Voyage's models are asymmetric, so use
        the right side for each call (improves retrieval quality).
        """
        result = self._client_().embed(
            texts=texts,
            model=EMBEDDING_MODEL,
            input_type=input_type,
        )
        return result.embeddings
