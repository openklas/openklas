from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models.document import Document
from app.schemas.rag import DocumentResponse, IngestResponse, QueryRequest, QueryResponse
from app.services.rag_service import delete_document, ingest_pdf, query_rag

router = APIRouter()

_PDF_MIME = "application/pdf"
_MAX_SIZE = 50 * 1024 * 1024  # 50 MB


@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest(
    current_user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
    subject_code: Optional[str] = Form(default=None),
):
    """Upload a PDF to be chunked, embedded, and stored for RAG queries."""
    if file.content_type != _PDF_MIME and not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    content = await file.read()
    if len(content) > _MAX_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds the 50 MB limit.")

    try:
        doc = await ingest_pdf(
            db=db,
            user_id=current_user.id,
            filename=file.filename or "upload.pdf",
            content=content,
            subject_code=subject_code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return IngestResponse(
        document_id=doc.id,
        filename=doc.filename,
        subject_code=doc.subject_code,
        total_chunks=doc.total_chunks,
        created_at=doc.created_at,
    )


@router.get("/documents", response_model=list[DocumentResponse])
async def list_documents(current_user: CurrentUser, db: DbSession):
    """List all documents ingested by the current user."""
    result = await db.execute(
        select(Document)
        .where(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc())
    )
    return result.scalars().all()


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document(document_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    """Delete a document and all its chunks."""
    deleted = await delete_document(db, current_user.id, document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found.")


@router.post("/query", response_model=QueryResponse)
async def query(body: QueryRequest, current_user: CurrentUser, db: DbSession):
    """Ask a question against your ingested lecture materials."""
    answer = await query_rag(
        db=db,
        user_id=current_user.id,
        question=body.question,
        subject_code=body.subject_code,
        top_k=body.top_k,
    )
    return QueryResponse(question=body.question, answer=answer)
