from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class IngestResponse(BaseModel):
    document_id: uuid.UUID
    filename: str
    subject_code: Optional[str]
    total_chunks: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    subject_code: Optional[str]
    total_chunks: int
    created_at: datetime

    model_config = {"from_attributes": True}


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    subject_code: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)


class QueryResponse(BaseModel):
    question: str
    answer: str
