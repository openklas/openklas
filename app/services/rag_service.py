from __future__ import annotations

import re
import uuid
from io import BytesIO

import pdfplumber
from ollama import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.services.embedding_service import EmbeddingService

OLLAMA_MODEL = "llama3.2"
MAX_CHUNK_SIZE = 1500
MIN_CHUNK_SIZE = 100
RETRIEVAL_TOP_K = 20
RERANK_TOP_K = 5

_ollama = AsyncClient()


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
    embeddings = svc.embed(texts)

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
    top_k: int = RERANK_TOP_K,
) -> str:
    svc = EmbeddingService.get()
    q_embedding = svc.embed([question])[0]

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
        .limit(RETRIEVAL_TOP_K)
    )

    result = await db.execute(stmt)
    candidates = result.scalars().all()

    if not candidates:
        return "No relevant materials found. Upload some PDFs first with POST /api/rag/ingest."

    passages = [c.content for c in candidates]
    top_indices = svc.rerank(question, passages, top_k=top_k)
    top_chunks = [candidates[i] for i in top_indices]

    context = "\n\n---\n\n".join(c.content for c in top_chunks)
    prompt = (
        "You are a helpful study assistant. Answer the question using only the provided "
        "lecture material context. If the answer is not in the context, say so.\n\n"
        f"CONTEXT:\n{context}\n\n"
        f"QUESTION: {question}"
    )

    response = await _ollama.chat(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.message.content


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
