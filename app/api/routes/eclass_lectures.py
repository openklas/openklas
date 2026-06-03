"""EClass lecture endpoints"""
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status, Depends

from app.api.deps import get_klas_service, get_session_data, CurrentUserFromKlas, DbSession
from app.core.rate_limit import limiter
from app.schemas.eclass_lecture import (
    EClassLectureItem,
    EClassLectureListResponse,
    CourseEClassLectures,
    AllEClassLecturesResponse,
)
from app.schemas.recorded_lecture import SummarizeJobResponse, SummarizeStatusResponse
from app.services.klas_service import KLASService
from app.services.summarize_service import (
    get_eclass_summarize_status,
    start_summarize_eclass_background,
)
from app.services.rag_service import find_document, get_document_text

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=EClassLectureListResponse)
async def list_eclass_lectures(
    subject_code: str = Query(..., description="Subject code (e.g. U202610969I030023)"),
    year: Optional[int] = Query(None, description="Academic year. Defaults to current."),
    semester: Optional[str] = Query(None, description="Semester: '1' or '2'. Defaults to current."),
    klas: KLASService = Depends(get_klas_service),
):
    """
    Get eclass lecture list for a subject.

    Returns all lectures sorted by serial descending (most recent first).
    Each item includes a `video_url` pointing directly to the MP4.

    Requires: Bearer token in Authorization header
    """
    try:
        raw = klas.get_eclass_lectures(subject_code, year, semester)
        items = [EClassLectureItem.model_validate(item) for item in raw]
        return EClassLectureListResponse(
            success=True,
            subject_code=subject_code,
            items=items,
            total=len(items),
        )
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching eclass lectures: {str(e)}")


@router.get("/all", response_model=AllEClassLecturesResponse, operation_id="list_all_eclass_lectures")
async def list_all_eclass_lectures(
    year: Optional[int] = Query(None, description="Academic year. Defaults to current."),
    semester: Optional[str] = Query(None, description="Semester: '1' or '2'. Defaults to current."),
    klas: KLASService = Depends(get_klas_service),
):
    """
    Get eclass lecture list for all enrolled subjects in one call.

    Fetches the timetable to discover subject codes, then retrieves eclass
    lectures for each subject.

    Requires: Bearer token in Authorization header
    """
    try:
        if year is None or semester is None:
            year, semester = klas.get_current_year_semester()

        timetable_data = klas.get_timetable(year, semester)
        courses = klas.parse_timetable(timetable_data)

        result: list[CourseEClassLectures] = []
        for course_code, course_info in courses.items():
            try:
                raw = klas.get_eclass_lectures(course_code, year, semester)
                items = [EClassLectureItem.model_validate(item) for item in raw]
            except Exception as e:
                logger.warning("eclass lectures failed for %s: %s", course_code, e)
                items = []
            result.append(CourseEClassLectures(
                course_code=course_code,
                course_title=course_info["course_title"],
                items=items,
            ))

        return AllEClassLecturesResponse(success=True, courses=result)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching eclass lectures: {str(e)}")


@router.post("/summarize", response_model=SummarizeJobResponse, operation_id="summarize_eclass_lecture", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("3/minute")
async def summarize_eclass_lecture(
    request: Request,
    background_tasks: BackgroundTasks,
    subject_code: str = Query(..., description="Subject code (e.g. U202610969I030023)"),
    content_id: str = Query(..., description="contentId from eclass lecture list"),
    year: Optional[int] = Query(None),
    semester: Optional[str] = Query(None),
    force: bool = Query(False, description="Re-summarize even if a cached summary exists"),
    session: dict = Depends(get_session_data),
    user: CurrentUserFromKlas = None,
    db: DbSession = None,
):
    """
    Summarize a single eclass lecture video in the background.

    Pipeline: download MP4 → transcribe (Groq Whisper) → summarize (Claude) → save to Obsidian.
    Returns immediately. Check progress at GET /api/eclass-lectures/summarize/status.

    Get subject_code and content_id from GET /api/eclass-lectures/all.

    Requires: Bearer token in Authorization header
    """
    klas = session["klas"]
    student_id = session["student_id"]
    password = session.get("password", "")

    job_status = get_eclass_summarize_status(student_id)
    if job_status.running and not force:
        raise HTTPException(
            status_code=409,
            detail="An eclass summarize job is already running. Check /summarize/status or pass force=true.",
        )

    try:
        if year is None or semester is None:
            year, semester = klas.get_current_year_semester()

        raw = klas.get_eclass_lectures(subject_code, year, semester)
        lecture = next((r for r in raw if r.get("contentId") == content_id), None)
        if not lecture:
            raise HTTPException(status_code=404, detail=f"EClass lecture {content_id} not found in {subject_code}.")

        item = EClassLectureItem.model_validate(lecture)
        video_url = item.video_url
        title = item.title or content_id

        if not video_url:
            raise HTTPException(status_code=422, detail="Could not construct video URL for this lecture.")

        # Cache check
        if not force:
            cached_doc = await find_document(db, user.id, f"eclass:{subject_code}:{content_id}", subject_code)
            if cached_doc:
                cached_summary = await get_document_text(db, cached_doc)
                s = get_eclass_summarize_status(student_id)
                s.running = False
                s.oid = content_id
                s.title = title
                s.summary = cached_summary
                s.step = "done"
                s.error = None
                return SummarizeJobResponse(
                    success=True,
                    oid=content_id,
                    title=title,
                    message=(
                        f"Cached summary for '{title}' loaded — no re-processing needed. "
                        "Call summarize/status to read the full summary, or pass force=true to regenerate."
                    ),
                    estimated_seconds=0,
                    status_endpoint="/api/eclass-lectures/summarize/status",
                )

        timetable_data = klas.get_timetable(year, semester)
        courses = klas.parse_timetable(timetable_data)
        course_title = courses.get(subject_code, {}).get("course_title", subject_code)

        background_tasks.add_task(
            start_summarize_eclass_background,
            video_url, content_id, title, course_title,
            student_id, password, str(user.id), subject_code,
        )
        duration_min = (item.duration or 0) // 60
        return SummarizeJobResponse(
            success=True,
            oid=content_id,
            title=title,
            message=(
                f"Summarization started for '{title}' (~{duration_min} min video). "
                "Pipeline: download → transcribe → summarize. Runs in background — "
                "call summarize/status to check progress."
            ),
            estimated_seconds=max(300, duration_min * 30),
            status_endpoint="/api/eclass-lectures/summarize/status",
        )
    except HTTPException:
        raise
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/summarize/status", response_model=SummarizeStatusResponse, operation_id="eclass_summarize_status")
async def eclass_summarize_status(session: dict = Depends(get_session_data)):
    """
    Get the current status of the background eclass summarize pipeline.

    `step` values: downloading | transcribing | summarizing | saving | done | error

    Requires: Bearer token in Authorization header
    """
    s = get_eclass_summarize_status(session["student_id"])
    return SummarizeStatusResponse(
        running=s.running,
        oid=s.oid,
        title=s.title,
        step=s.step,
        transcript=s.transcript,
        summary=s.summary,
        obsidian_path=s.obsidian_path,
        error=s.error,
        started_at=s.started_at,
        finished_at=s.finished_at,
    )
