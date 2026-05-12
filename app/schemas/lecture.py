"""Lecture schemas"""
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import uuid


class LectureMaterialItem(BaseModel):
    id: uuid.UUID
    board_no: int
    subject_code: str
    subject_name: str
    year: int
    semester: str
    sort_order: int
    post_title: str
    file_name: str
    atch_file_id: str
    file_sn: int
    synced_at: datetime

    model_config = {"from_attributes": True}


class LectureListResponse(BaseModel):
    success: bool
    items: List[LectureMaterialItem] = []
    total: int = 0
    message: Optional[str] = None


class LectureSyncResponse(BaseModel):
    success: bool
    synced: int
    skipped: int
    failed: int
    message: Optional[str] = None


class LectureAskResponse(BaseModel):
    success: bool
    board_no: int
    post_title: str
    question: str
    answer: str
