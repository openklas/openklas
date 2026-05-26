"""Per-user PDF RAG pipeline.

Pipeline:
    PDF bytes
      → pdfplumber text extraction (page-aware)
      → semantic chunking (paragraph/heading boundaries)
      → Voyage AI embeddings
      → pgvector storage
      → cosine similarity retrieval
      → Anthropic Claude answer generation

The previous implementation used local Ollama + sentence-transformers, which
inflated the container image by ~3 GB and required a GPU for decent latency.
Hosted APIs replace both — see `embedding_service.py` for the embedder.
"""
from __future__ import annotations

import re
import uuid
from io import BytesIO

import pdfplumber
from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document, DocumentChunk
from app.services.embedding_service import EmbeddingService

# Generation model — Haiku is fast and cheap, plenty good for RAG synthesis.
ANSWER_MODEL = "claude-haiku-4-5"
MAX_CHUNK_SIZE = 1500
MIN_CHUNK_SIZE = 100
RETRIEVAL_TOP_K = 5

_anthropic = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)


def _semantic_chunks(text: str) -> list[str]:
    """Split text at paragraph/heading boundaries with sentence-level overflow splitting."""
    paragraphs = re.split(r"\n{2,}", text)
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(para) > MAX_CHUNK_SIZE:
            # Flush current buffer before handling large paragraph
            if len(current) >= MIN_CHUNK_SIZE:
                chunks.append(current.strip())
                current = ""
            for sent in re.split(r"(?<=[.!?])\s+", para):
                if len(current) + len(sent) > MAX_CHUNK_SIZE and len(current) >= MIN_CHUNK_SIZE:
                    chunks.append(current.strip())
                    current = sent
                else:
                    current = (current + " " + sent).strip() if current else sent
            continue

        if current and len(current) + len(para) > MAX_CHUNK_SIZE:
            if len(current) >= MIN_CHUNK_SIZE:
                chunks.append(current.strip())
            current = para
        else:
            current = (current + "\n\n" + para).strip() if current else para

    if len(current) >= MIN_CHUNK_SIZE:
        chunks.append(current.strip())

    return chunks


async def ingest_pdf(
    db: AsyncSession,
    user_id: uuid.UUID,
    filename: str,
    content: bytes,
    subject_code: str | None = None,
) -> Document:
    svc = EmbeddingService.get()

    page_chunks: list[tuple[str, int]] = []
    with pdfplumber.open(BytesIO(content)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for chunk in _semantic_chunks(text):
                page_chunks.append((chunk, page_no))

    if not page_chunks:
        raise ValueError("No extractable text found in the PDF.")

    texts = [t for t, _ in page_chunks]
    embeddings = svc.embed(texts, input_type="document")

    doc = Document(
        user_id=user_id,
        filename=filename,
        subject_code=subject_code,
        total_chunks=len(page_chunks),
    )
    db.add(doc)
    await db.flush()

    for idx, ((text, page_no), embedding) in enumerate(zip(page_chunks, embeddings)):
        db.add(DocumentChunk(
            document_id=doc.id,
            user_id=user_id,
            content=text,
            embedding=embedding,
            chunk_index=idx,
            page_number=page_no,
        ))

    await db.commit()
    await db.refresh(doc)
    return doc


async def query_rag(
    db: AsyncSession,
    user_id: uuid.UUID,
    question: str,
    subject_code: str | None = None,
    top_k: int = RETRIEVAL_TOP_K,
) -> str:
    svc = EmbeddingService.get()
    q_embedding = svc.embed([question], input_type="query")[0]

    stmt = (
        select(DocumentChunk)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(DocumentChunk.user_id == user_id)
    )
    if subject_code:
        stmt = stmt.where(Document.subject_code == subject_code)

    stmt = (
        stmt
        .order_by(DocumentChunk.embedding.cosine_distance(q_embedding))
        .limit(top_k)
    )

    result = await db.execute(stmt)
    top_chunks = result.scalars().all()

    if not top_chunks:
        return "No relevant materials found. Upload some PDFs first with POST /api/rag/ingest."

    context = "\n\n---\n\n".join(c.content for c in top_chunks)
    prompt = (
        "You are a helpful study assistant. Answer the question using only the provided "
        "lecture material context. If the answer is not in the context, say so.\n\n"
        f"CONTEXT:\n{context}\n\n"
        f"QUESTION: {question}"
    )

    response = await _anthropic.messages.create(
        model=ANSWER_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


async def ingest_text(
    db: AsyncSession,
    user_id: uuid.UUID,
    filename: str,
    text: str,
    subject_code: str | None = None,
) -> Document:
    """Chunk, embed, and store plain text as a searchable RAG document."""
    svc = EmbeddingService.get()
    chunks = _semantic_chunks(text)
    if not chunks:
        chunks = [text[:MAX_CHUNK_SIZE]] if text.strip() else []
    if not chunks:
        raise ValueError("No text content to ingest.")
    embeddings = svc.embed(chunks, input_type="document")
    doc = Document(user_id=user_id, filename=filename, subject_code=subject_code, total_chunks=len(chunks))
    db.add(doc)
    await db.flush()
    for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        db.add(DocumentChunk(
            document_id=doc.id, user_id=user_id,
            content=chunk, embedding=embedding, chunk_index=idx,
        ))
    await db.commit()
    await db.refresh(doc)
    return doc


async def find_document(
    db: AsyncSession,
    user_id: uuid.UUID,
    filename: str,
    subject_code: str | None = None,
) -> Document | None:
    """Return an existing document by user + filename (+ optional subject_code), or None."""
    stmt = select(Document).where(Document.user_id == user_id, Document.filename == filename)
    if subject_code:
        stmt = stmt.where(Document.subject_code == subject_code)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_document_text(db: AsyncSession, document: Document) -> str:
    """Reconstruct the full text of a document by joining its chunks in order."""
    result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index)
    )
    return "\n\n".join(c.content for c in result.scalars().all())


async def delete_document(db: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return False
    await db.delete(doc)
    await db.commit()
    return True
