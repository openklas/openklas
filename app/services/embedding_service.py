from __future__ import annotations

import numpy as np
from sentence_transformers import CrossEncoder, SentenceTransformer

# Swap EMBEDDING_MODEL for a multilingual one (e.g. paraphrase-multilingual-MiniLM-L12-v2)
# if your PDFs contain Korean text.
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class EmbeddingService:
    _instance: EmbeddingService | None = None
    _embedder: SentenceTransformer | None = None
    _reranker: CrossEncoder | None = None

    @classmethod
    def get(cls) -> EmbeddingService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _embedder_(self) -> SentenceTransformer:
        if self._embedder is None:
            self._embedder = SentenceTransformer(EMBEDDING_MODEL)
        return self._embedder

    def _reranker_(self) -> CrossEncoder:
        if self._reranker is None:
            self._reranker = CrossEncoder(RERANKER_MODEL)
        return self._reranker

    def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings = self._embedder_().encode(texts, normalize_embeddings=True)
        return embeddings.tolist()

    def rerank(self, query: str, passages: list[str], top_k: int) -> list[int]:
        """Return indices of the top_k passages ranked by relevance score."""
        scores = self._reranker_().predict([[query, p] for p in passages])
        ranked = np.argsort(scores)[::-1][:top_k]
        return ranked.tolist()
