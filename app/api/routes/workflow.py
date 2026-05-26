"""Workflow summary endpoint"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_session
from app.db.session import get_db
from app.models.document import Document
from app.models.user import User
from app.schemas.workflow import (
    PendingHomework,
    RecentSummary,
    TodayCourse,
    WorkflowSummary,
)
from app.services.klas_service import KLASService
from app.services.summarize_service import get_summarize_status
from app.api.deps import get_session_data

router = APIRouter()
security = HTTPBearer(auto_error=False)

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


async def _get_klas_and_student(
    session: dict = Depends(get_session_data),
) -> tuple[KLASService, str]:
    return session["klas"], session["student_id"]


@router.get("/summary", response_model=WorkflowSummary)
async def get_workflow_summary(
    year: Optional[int] = Query(None),
    semester: Optional[str] = Query(None),
    session: tuple[KLASService, str] = Depends(_get_klas_and_student),
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregated academic workflow summary for the authenticated student.

    Returns:
    - **today_courses**: classes scheduled for today
    - **pending_homework**: unsubmitted assignments across all subjects, sorted by deadline
    - **recent_summary**: latest recorded-lecture summarization job status
    - **rag_document_count**: number of PDFs ingested into the student's RAG store

    Requires: Bearer token (KLAS session token) in Authorization header.
    """
    klas, student_id = session
    now = datetime.now()
    today_day_num = now.weekday()  # 0=Monday … 6=Sunday

    try:
        if year is None or semester is None:
            year, semester = klas.get_current_year_semester()

        timetable_data = klas.get_timetable(year, semester)
        courses = klas.parse_timetable(timetable_data)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"KLAS service unavailable: {e}")

    # --- Today's courses ---
    today_courses: list[TodayCourse] = []
    for code, info in courses.items():
        for sched in info.get("schedules", []):
            if sched.get("day_num") == today_day_num:
                today_courses.append(TodayCourse(
                    course_code=code,
                    course_title=info["course_title"],
                    start_time=sched["start_time"],
                    end_time=sched["end_time"],
                    location=sched["location"],
                    professor=sched["professor"],
                ))
    today_courses.sort(key=lambda c: c.start_time)

    # --- Pending (unsubmitted) homework ---
    pending: list[PendingHomework] = []
    for code, info in courses.items():
        try:
            raw_hw = klas.get_homework(code, year, semester)
        except Exception:
            continue
        for item in raw_hw:
            if item.get("submityn", "Y") == "N":
                pending.append(PendingHomework(
                    course_code=code,
                    course_title=info["course_title"],
                    title=item["title"],
                    task_no=item["taskNo"],
                    expire_date=item.get("expiredate"),
                ))
    # Sort by deadline ascending (None deadlines go last)
    pending.sort(key=lambda h: h.expire_date or "9999-99-99")

    # --- Most recent summarize job ---
    status_obj = get_summarize_status(student_id)
    recent_summary: Optional[RecentSummary] = None
    if status_obj.step:
        recent_summary = RecentSummary(
            title=status_obj.title,
            step=status_obj.step,
            summary=status_obj.summary,
            obsidian_path=status_obj.obsidian_path,
            finished_at=status_obj.finished_at,
        )

    # --- RAG document count ---
    user_result = await db.execute(select(User).where(User.student_id == student_id))
    user = user_result.scalar_one_or_none()
    rag_count = 0
    if user:
        count_result = await db.execute(
            select(func.count()).select_from(Document).where(Document.user_id == user.id)
        )
        rag_count = count_result.scalar_one() or 0

    return WorkflowSummary(
        success=True,
        generated_at=now.isoformat(),
        today=_DAY_NAMES[today_day_num],
        today_courses=today_courses,
        pending_homework=pending,
        recent_summary=recent_summary,
        rag_document_count=rag_count,
    )
