"""Recorded lecture endpoints"""
import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

logger = logging.getLogger(__name__)

from app.core.security import get_session
from app.services.klas_service import KLASService
from app.schemas.recorded_lecture import (
    RecordedLectureItem,
    RecordedLectureListResponse,
    CourseRecordedLectures,
    AllRecordedLecturesResponse,
)

router = APIRouter()
security = HTTPBearer(auto_error=False)


def get_klas_service(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    token: Optional[str] = Query(None, description="Session token (alternative to Authorization header)"),
) -> KLASService:
    raw_token = token or (credentials.credentials if credentials else None)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session_data = get_session(raw_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return session_data["klas"]


@router.get("", response_model=RecordedLectureListResponse)
async def list_recorded_lectures(
    subject_code: str = Query(..., description="Subject code (e.g. U202610846I030014)"),
    year: Optional[int] = Query(None, description="Academic year (e.g. 2026). Defaults to current year."),
    semester: Optional[str] = Query(None, description="Semester: '1' for Spring, '2' for Fall. Defaults to current."),
    klas: KLASService = Depends(get_klas_service),
):
    """
    Get recorded (online) lecture list for a subject.

    Returns all lessons sorted by week number then weekly sequence.
    Each item includes the playback URL (`starting`), progress (`prog` 0-100),
    and learn/total time in minutes.

    Requires: Bearer token in Authorization header
    """
    try:
        raw = klas.get_recorded_lectures(subject_code, year, semester)
        items = [RecordedLectureItem.model_validate(item) for item in raw]
        return RecordedLectureListResponse(
            success=True,
            subject_code=subject_code,
            items=items,
            total=len(items),
        )
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching recorded lectures: {str(e)}")


@router.get("/all", response_model=AllRecordedLecturesResponse)
async def list_all_recorded_lectures(
    year: Optional[int] = Query(None, description="Academic year. Defaults to current year."),
    semester: Optional[str] = Query(None, description="Semester: '1' or '2'. Defaults to current."),
    klas: KLASService = Depends(get_klas_service),
):
    """
    Get recorded lecture list for all enrolled subjects in one call.

    Fetches the timetable to discover subject codes, then retrieves recorded
    lectures for each subject.

    Requires: Bearer token in Authorization header
    """
    try:
        if year is None or semester is None:
            year, semester = klas.get_current_year_semester()

        timetable_data = klas.get_timetable(year, semester)
        courses = klas.parse_timetable(timetable_data)

        result: list[CourseRecordedLectures] = []
        for course_code, course_info in courses.items():
            try:
                raw = klas.get_recorded_lectures(course_code, year, semester)
                items = [RecordedLectureItem.model_validate(item) for item in raw]
            except Exception as e:
                logger.warning("recorded lectures failed for %s: %s", course_code, e)
                items = []
            result.append(CourseRecordedLectures(
                course_code=course_code,
                course_title=course_info["course_title"],
                items=items,
            ))

        return AllRecordedLecturesResponse(success=True, courses=result)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching recorded lectures: {str(e)}")
