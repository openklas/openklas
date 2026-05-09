"""Homework endpoints"""
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

from app.schemas.homework import HomeworkResponse, HomeworkItem
from app.core.security import get_session
from app.services.klas_service import KLASService

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


@router.get("", response_model=HomeworkResponse)
async def get_homework(
    subject_code: str = Query(..., description="Subject code (e.g. U202618484I030032)"),
    year: Optional[int] = Query(None, description="Academic year (e.g. 2026). Defaults to current year."),
    semester: Optional[str] = Query(None, description="Semester: '1' for Spring, '2' for Fall. Defaults to current."),
    klas: KLASService = Depends(get_klas_service),
):
    """
    Get homework list for a subject, sorted by most recent first (highest taskNo).

    - **subject_code**: Subject code from timetable (required)
    - **year**: Academic year (optional, defaults to current)
    - **semester**: '1' or '2' (optional, defaults to current)

    Requires: Bearer token in Authorization header
    """
    try:
        raw = klas.get_homework(subject_code, year, semester)
        items = [HomeworkItem.model_validate(item) for item in raw]
        return HomeworkResponse(success=True, subject_code=subject_code, items=items)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching homework: {str(e)}")
