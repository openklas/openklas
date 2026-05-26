"""
Timetable endpoints
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

from app.schemas.timetable import TimetableResponse
from app.schemas.session import SessionInfo
from app.schemas.university_schedule import UniversityScheduleItem, UniversityScheduleResponse
from app.services.klas_service import KLASService
from app.api.deps import get_klas_service, get_session_data

router = APIRouter()
security = HTTPBearer(auto_error=False)


@router.get("", response_model=TimetableResponse)
async def get_timetable(
    year: Optional[int] = None,
    semester: Optional[str] = None,
    klas: KLASService = Depends(get_klas_service)
):
    """
    Get your timetable for a specific year and semester
    
    - **year**: Academic year (e.g., 2025). If not specified, uses current year.
    - **semester**: Semester ("1" for Spring, "2" for Fall). If not specified, uses current semester.
    
    Requires: Bearer token in Authorization header
    """
    try:
        # Fetch timetable data
        timetable_data = klas.get_timetable(year, semester)
        
        # Parse into structured format
        courses = klas.parse_timetable(timetable_data)
        
        if courses:
            return TimetableResponse(
                success=True,
                courses=courses
            )
        else:
            return TimetableResponse(
                success=False,
                message="No courses found for this semester"
            )
            
    except ConnectionError as e:
        raise HTTPException(
            status_code=503,
            detail=f"KLAS service unavailable: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching timetable: {str(e)}"
        )


@router.get("/schedule", response_model=UniversityScheduleResponse, operation_id="get_university_schedule")
async def get_university_schedule(
    start_date: str,
    end_date: str,
    klas: KLASService = Depends(get_klas_service),
):
    """
    Get university academic schedule (학사일정) for a date range from KLAS.

    - **start_date**: Start date YYYY-MM-DD (e.g. 2026-03-01).
    - **end_date**: End date YYYY-MM-DD (e.g. 2026-06-30).

    Requires: Bearer token in Authorization header (KLAS session).
    """
    try:
        raw_items = klas.get_university_schedule(start_date=start_date, end_date=end_date)
        items = [UniversityScheduleItem.model_validate(item) for item in raw_items]
        return UniversityScheduleResponse(
            success=True,
            start_date=start_date,
            end_date=end_date,
            items=items,
        )
    except ConnectionError as e:
        raise HTTPException(
            status_code=503,
            detail=f"KLAS service unavailable: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching university schedule: {str(e)}",
        )


@router.get("/session/info", response_model=SessionInfo)
async def get_session_info(session: dict = Depends(get_session_data)):
    """
    Get information about your current session

    Requires: Bearer token in Authorization header
    """
    expires_at = session['expires_at']
    now = datetime.now()
    time_remaining = max(timedelta(0), expires_at - now)

    from app.core.config import settings as _cfg
    created_at = session.get('created_at') or (expires_at - timedelta(hours=_cfg.SESSION_EXPIRE_HOURS))

    return SessionInfo(
        student_id=session['student_id'],
        created_at=created_at.isoformat(),
        expires_at=expires_at.isoformat(),
        time_remaining=str(time_remaining)
    )

