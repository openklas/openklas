"""Workflow summary schemas"""
from pydantic import BaseModel
from typing import List, Optional


class TodayCourse(BaseModel):
    course_code: str
    course_title: str
    start_time: str
    end_time: str
    location: str
    professor: str


class PendingHomework(BaseModel):
    course_code: str
    course_title: str
    title: str
    task_no: int
    expire_date: Optional[str] = None


class RecentSummary(BaseModel):
    title: Optional[str] = None
    step: str
    summary: Optional[str] = None
    obsidian_path: Optional[str] = None
    finished_at: Optional[str] = None


class WorkflowSummary(BaseModel):
    success: bool
    generated_at: str
    today: str
    today_courses: List[TodayCourse] = []
    pending_homework: List[PendingHomework] = []
    recent_summary: Optional[RecentSummary] = None
    rag_document_count: int = 0
