"""Recorded lecture endpoints"""
import logging
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, Query
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
    WatchJobResponse,
    WatchStatusResponse,
    SummarizeJobResponse,
    SummarizeStatusResponse,
    AutocompleteJobResponse,
    AutocompleteStatusResponse,
)
from app.services.watch_service import get_unwatched, start_watch_background, get_status, reset_status
from app.services.summarize_service import get_summarize_status, start_summarize_background
from app.services.progress_service import get_autocomplete_status, start_autocomplete_background
from app.core.security import get_session as _get_session

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


def get_session_data(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    token: Optional[str] = Query(None),
) -> dict:
    raw_token = token or (credentials.credentials if credentials else None)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session_data = get_session(raw_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return session_data


@router.post("/watch", response_model=WatchJobResponse)
async def watch_lecture(
    background_tasks: BackgroundTasks,
    subject_code: str = Query(..., description="Subject code from timetable"),
    oid: str = Query(..., description="Lecture oid from the recorded lecture list"),
    year: Optional[int] = Query(None),
    semester: Optional[str] = Query(None),
    force: bool = Query(False, description="Override a stuck/stale watch job"),
    session: dict = Depends(get_session_data),
):
    """
    Start auto-watching a single recorded lecture in the background.

    Get `subject_code` and `oid` from `GET /api/recorded-lectures/all`.
    Opens a headless browser, plays the video at 2x speed, and lets KLAS
    record the progress. Returns immediately — watching happens in the background.

    Requires: Bearer token in Authorization header
    """
    klas = session["klas"]
    student_id = session["student_id"]
    password = session.get("password", "")

    try:
        if year is None or semester is None:
            year, semester = klas.get_current_year_semester()

        if get_status().running and not force:
            raise HTTPException(status_code=409, detail="A lecture is already being watched. Check /watch/status or pass force=true to override.")

        items = klas.get_recorded_lectures(subject_code, year, semester)
        lecture = next((i for i in items if i.get("oid") == oid), None)
        if not lecture:
            raise HTTPException(status_code=404, detail=f"Lecture {oid} not found in {subject_code}.")

        url = lecture.get("starting")
        if not url:
            raise HTTPException(status_code=422, detail="This lecture has no playback URL.")

        total_min = int(lecture.get("totalTime") or lecture.get("rcognTime") or 30)
        payload = {"title": lecture.get("sbjt", oid), "url": url, "total_min": total_min, "prog": lecture.get("prog", 0)}

        background_tasks.add_task(start_watch_background, klas, [payload], student_id, password)
        return WatchJobResponse(
            success=True,
            watching=1,
            lectures=[payload["title"]],
            message=f"Watching '{payload['title']}' in the background (~{total_min} min at 2x = ~{total_min//2} min).",
        )
    except HTTPException:
        raise
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/watch/status", response_model=WatchStatusResponse)
async def watch_status(klas: KLASService = Depends(get_klas_service)):
    """
    Get the current status of the background watch job.

    Requires: Bearer token in Authorization header
    """
    s = get_status()
    return WatchStatusResponse(
        running=s.running,
        total=s.total,
        completed=s.completed,
        in_progress=s.in_progress,
        pending=s.pending,
        failed=s.failed,
        started_at=s.started_at,
        finished_at=s.finished_at,
    )


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


@router.post("/summarize", response_model=SummarizeJobResponse)
async def summarize_recorded_lecture(
    background_tasks: BackgroundTasks,
    subject_code: str = Query(..., description="Subject code (e.g. U202610846I030014)"),
    oid: str = Query(..., description="Lecture oid from the recorded lecture list"),
    year: Optional[int] = Query(None),
    semester: Optional[str] = Query(None),
    force: bool = Query(False, description="Override a stuck/stale summarize job"),
    session: dict = Depends(get_session_data),
):
    """
    Start the video summarization pipeline for a single recorded lecture in the background.

    Steps: download MP4 → transcribe (faster-whisper) → summarize (Claude) → save to Obsidian.
    Returns immediately. Check progress at `GET /summarize/status`.

    Get `subject_code` and `oid` from `GET /api/recorded-lectures/all`.

    Requires: Bearer token in Authorization header
    """
    klas = session["klas"]
    student_id = session["student_id"]
    password = session.get("password", "")

    status = get_summarize_status()
    if status.running and not force:
        raise HTTPException(
            status_code=409,
            detail="A summarize job is already running. Check /summarize/status or pass force=true.",
        )

    try:
        if year is None or semester is None:
            year, semester = klas.get_current_year_semester()

        # Resolve course title from timetable
        timetable_data = klas.get_timetable(year, semester)
        courses = klas.parse_timetable(timetable_data)
        course_title = courses.get(subject_code, {}).get("course_title", subject_code)

        # Find the specific lecture
        items = klas.get_recorded_lectures(subject_code, year, semester)
        lecture = next((i for i in items if i.get("oid") == oid), None)
        if not lecture:
            raise HTTPException(status_code=404, detail=f"Lecture {oid} not found in {subject_code}.")

        starting = lecture.get("starting")
        if not starting:
            raise HTTPException(status_code=422, detail="This lecture has no playback URL.")

        title = lecture.get("sbjt", oid)
        week_no = lecture.get("weekNo")

        background_tasks.add_task(
            start_summarize_background,
            starting, oid, title, course_title, week_no, student_id, password,
        )
        return SummarizeJobResponse(
            success=True,
            oid=oid,
            title=title,
            message=f"Summarize pipeline started for '{title}'. Check /summarize/status for progress.",
        )
    except HTTPException:
        raise
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/summarize/status", response_model=SummarizeStatusResponse)
async def summarize_status(klas: KLASService = Depends(get_klas_service)):
    """
    Get the current status of the background summarize pipeline.

    `step` values: downloading | transcribing | summarizing | saving | done | error

    Requires: Bearer token in Authorization header
    """
    s = get_summarize_status()
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


@router.post("/autocomplete", response_model=AutocompleteJobResponse)
async def autocomplete_lecture(
    background_tasks: BackgroundTasks,
    subject_code: str = Query(..., description="Subject code from timetable"),
    oid: str = Query(..., description="Lecture oid from the recorded lecture list"),
    year: Optional[int] = Query(None),
    semester: Optional[str] = Query(None),
    delay: float = Query(3.0, description="Seconds between UpdateProgress calls (lower = faster)"),
    force: bool = Query(False, description="Override a stuck/stale autocomplete job"),
    session: dict = Depends(get_session_data),
):
    """
    Mark a single recorded lecture as complete by directly calling the KLAS
    progress API — no browser or video playback required.

    The service opens the viewer (to obtain a `lecKey`), then rapidly calls
    `UpdateProgress.do` with increasing video positions until KLAS reports
    `prog ≥ 100` or `lessonstatus = passed`.

    `delay` controls seconds between calls. Default 3s. Reduce to 1s for
    maximum speed; increase if KLAS starts returning errors.

    Requires: Bearer token in Authorization header
    """
    klas = session["klas"]
    student_id = session["student_id"]

    status = get_autocomplete_status()
    if status.running and not force:
        raise HTTPException(
            status_code=409,
            detail="An autocomplete job is already running. Check /autocomplete/status or pass force=true.",
        )

    try:
        if year is None or semester is None:
            year, semester = klas.get_current_year_semester()

        raw_list = klas.get_recorded_lectures(subject_code, year, semester)
        raw = next((r for r in raw_list if r.get("oid") == oid), None)
        if not raw:
            raise HTTPException(status_code=404, detail=f"Lecture {oid} not found in {subject_code}.")

        title = raw.get("sbjt", oid)
        background_tasks.add_task(
            start_autocomplete_background,
            klas, [raw], str(year), semester, student_id, delay,
        )
        return AutocompleteJobResponse(
            success=True,
            watching=1,
            lectures=[title],
            message=f"Autocomplete started for '{title}'. Check /autocomplete/status for progress.",
        )
    except HTTPException:
        raise
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/autocomplete/all", response_model=AutocompleteJobResponse)
async def autocomplete_all_lectures(
    background_tasks: BackgroundTasks,
    year: Optional[int] = Query(None),
    semester: Optional[str] = Query(None),
    delay: float = Query(3.0, description="Seconds between UpdateProgress calls per lecture"),
    force: bool = Query(False),
    session: dict = Depends(get_session_data),
):
    """
    Mark ALL incomplete recorded lectures across all enrolled subjects as complete.

    Iterates every subject from the timetable, skips lectures already at 100%,
    and runs the progress API loop for each remaining one sequentially.

    Requires: Bearer token in Authorization header
    """
    klas = session["klas"]
    student_id = session["student_id"]

    status = get_autocomplete_status()
    if status.running and not force:
        raise HTTPException(
            status_code=409,
            detail="An autocomplete job is already running. Check /autocomplete/status.",
        )

    try:
        if year is None or semester is None:
            year, semester = klas.get_current_year_semester()

        timetable = klas.get_timetable(year, semester)
        courses = klas.parse_timetable(timetable)

        incomplete: list[dict] = []
        for course_code in courses:
            try:
                items = klas.get_recorded_lectures(course_code, year, semester)
                for item in items:
                    if item.get("oid") and (item.get("prog") or 0) < 100:
                        incomplete.append(item)
            except Exception:
                continue

        if not incomplete:
            return AutocompleteJobResponse(
                success=True,
                watching=0,
                lectures=[],
                message="All lectures are already complete.",
            )

        titles = [r.get("sbjt", r.get("oid", "?")) for r in incomplete]
        background_tasks.add_task(
            start_autocomplete_background,
            klas, incomplete, str(year), semester, student_id, delay,
        )
        return AutocompleteJobResponse(
            success=True,
            watching=len(incomplete),
            lectures=titles,
            message=f"Autocomplete started for {len(incomplete)} lecture(s). Check /autocomplete/status.",
        )
    except HTTPException:
        raise
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/autocomplete/status", response_model=AutocompleteStatusResponse)
async def autocomplete_status(klas: KLASService = Depends(get_klas_service)):
    """
    Poll the current autocomplete job status.

    `current_prog` is the live progress % of the lecture being processed.

    Requires: Bearer token in Authorization header
    """
    s = get_autocomplete_status()
    return AutocompleteStatusResponse(
        running=s.running,
        total=s.total,
        completed=s.completed,
        in_progress=s.in_progress,
        pending=s.pending,
        failed=s.failed,
        current_prog=s.current_prog,
        started_at=s.started_at,
        finished_at=s.finished_at,
    )
