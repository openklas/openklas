"""Background service that marks KLAS recorded lectures as watched via direct HTTP calls.

Flow (reverse-engineered from KLAS JS):
  1. POST LctreCntntsViewSpvPage.do  → HTML containing lecKey (bcrypt token)
  2. Every 60 s: POST UpdateProgress.do  → returns prog (%)
  3. Every 60 s: POST ChkLctreCntntsView.do  → duplicate-session check
  4. Every 10 min: GET klas homepage + Frame.do  → keepalive
  5. Stop when prog >= 100 or totalTime elapsed
"""
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.services.klas_service import KLASService

logger = logging.getLogger(__name__)

_VIEWER_BASE = "https://klas.kw.ac.kr/spv/lis/lctre/viewer"
_KLAS_BASE = "https://klas.kw.ac.kr"
_UPDATE_INTERVAL = 60  # seconds — matches KLAS JS setInterval


# ── In-memory job state ───────────────────────────────────────────────────────

@dataclass
class WatchStatus:
    running: bool = False
    total: int = 0
    completed: list[str] = field(default_factory=list)
    in_progress: Optional[str] = None
    pending: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


_statuses: dict[str, WatchStatus] = {}


def get_status(student_id: str) -> WatchStatus:
    return _statuses.get(student_id) or WatchStatus()


def _ensure_status(student_id: str) -> WatchStatus:
    s = _statuses.get(student_id)
    if s is None:
        s = WatchStatus()
        _statuses[student_id] = s
    return s


def reset_status(student_id: str) -> None:
    s = _statuses.get(student_id)
    if s is None:
        return
    s.running = False
    s.in_progress = None
    s.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _reset(lectures: list[dict], student_id: str) -> None:
    s = _ensure_status(student_id)
    s.running = True
    s.total = len(lectures)
    s.completed = []
    s.in_progress = None
    s.pending = [lec["title"] for lec in lectures]
    s.failed = []
    s.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    s.finished_at = None


# ── Item helpers ──────────────────────────────────────────────────────────────

def enrich_item(item: dict) -> dict:
    """Flatten a raw KLAS recorded-lecture item into the shape watch_service needs."""
    return {
        "title":        item.get("sbjt") or item.get("oid") or "Unknown",
        "url":          item.get("starting", ""),
        "total_min":    int(item.get("totalTime") or item.get("rcognTime") or 30),
        "prog":         item.get("prog", 0),
        # Fields required by LctreCntntsViewSpvPage.do / UpdateProgress.do
        "grcode":       item.get("grcode", "N000003"),
        "subj":         item.get("subj", ""),
        "year":         str(item.get("year", "")),
        "hakgi":        str(item.get("hakgi", "")),
        "bunban":       str(item.get("bunban", "01")),
        "module":       str(item.get("module", "")),
        "lesson":       str(item.get("lesson", "")),
        "oid":          item.get("oid", ""),
        "weeklyseq":    str(item.get("weeklyseq", "")),
        "weeklysubseq": str(item.get("weeklysubseq", "1")),
    }


# ── KLAS HTTP helpers ─────────────────────────────────────────────────────────

def _open_viewer(klas: KLASService, lecture: dict) -> str:
    """POST to the viewer page and extract the lecKey from embedded JS."""
    params = {
        "grcode":       lecture["grcode"],
        "subj":         lecture["subj"],
        "year":         lecture["year"],
        "hakgi":        lecture["hakgi"],
        "bunban":       lecture["bunban"],
        "module":       lecture["module"],
        "lesson":       lecture["lesson"],
        "oid":          lecture["oid"],
        "ptime":        1,
        "weeklyseq":    lecture["weeklyseq"],
        "weeklysubseq": lecture["weeklysubseq"],
        "totalTime":    0,
        "prog":         0,
        "profYN":       "N",
        "previewYN":    "N",
        "late":         "N",
    }
    resp = klas.session.post(f"{_VIEWER_BASE}/LctreCntntsViewSpvPage.do", data=params)
    resp.raise_for_status()

    match = re.search(r'"lecKey"\s*:\s*\'([^\']+)\'', resp.text)
    if not match:
        raise ValueError(f"lecKey not found in viewer page for oid={lecture['oid']}")

    lec_key = match.group(1)
    logger.info("Opened viewer for %s, lecKey=%.20s…", lecture["title"], lec_key)
    return lec_key


def _progress_params(lecture: dict, lec_key: str) -> dict:
    return {
        "year":         lecture["year"],
        "subj":         lecture["subj"],
        "bunban":       lecture["bunban"],
        "hakgi":        lecture["hakgi"],
        "module":       lecture["module"],
        "lesson":       lecture["lesson"],
        "oid":          lecture["oid"],
        "weeklyseq":    lecture["weeklyseq"],
        "weeklysubseq": lecture["weeklysubseq"],
        "grcode":       lecture["grcode"],
        "lecKey":       lec_key,
        "isendfile":    "Y",
    }


def _post_update(klas: KLASService, lecture: dict, lec_key: str) -> dict:
    resp = klas.session.post(
        f"{_VIEWER_BASE}/UpdateProgress.do",
        data=_progress_params(lecture, lec_key),
    )
    resp.raise_for_status()
    return resp.json()


def _post_chk(klas: KLASService, lecture: dict, lec_key: str) -> None:
    klas.session.post(
        f"{_VIEWER_BASE}/ChkLctreCntntsView.do",
        data=_progress_params(lecture, lec_key),
    )


def _keepalive(klas: KLASService, student_id: str) -> None:
    try:
        klas.session.get(f"{_KLAS_BASE}/")
        klas.session.post(
            f"{_KLAS_BASE}/std/cmn/frame/Frame.do",
            data={"storeId": student_id, "storeIdChecked": "checked"},
        )
        logger.info("Session keepalive sent")
    except Exception as e:
        logger.warning("Keepalive failed: %s", e)


# ── Core watch loop ───────────────────────────────────────────────────────────

def _watch_single(klas: KLASService, lecture: dict, student_id: str) -> None:
    title = lecture["title"]
    total_min = lecture["total_min"]

    s = _ensure_status(student_id)
    s.in_progress = title
    if title in s.pending:
        s.pending.remove(title)

    logger.info("Starting HTTP watch: %s (%d min)", title, total_min)

    lec_key = _open_viewer(klas, lecture)

    elapsed = 0
    keepalive_elapsed = 0
    # Add a 10% buffer beyond totalTime; KLAS considers <100% incomplete
    max_wait = (total_min + 5) * 60

    while elapsed < max_wait:
        time.sleep(_UPDATE_INTERVAL)
        elapsed += _UPDATE_INTERVAL
        keepalive_elapsed += _UPDATE_INTERVAL

        try:
            result = _post_update(klas, lecture, lec_key)
            prog = float(result.get("prog", 0))
            ptime = result.get("ptime", "?")
            logger.info("%s — prog=%.1f%% ptime=%ss elapsed=%ds", title, prog, ptime, elapsed)

            if result.get("redirect"):
                raise RuntimeError("KLAS session expired mid-watch")

            if prog >= 100:
                logger.info("✓ Completed: %s (prog=%.1f%%)", title, prog)
                break
        except Exception as e:
            logger.error("UpdateProgress error for %s: %s", title, e)

        try:
            _post_chk(klas, lecture, lec_key)
        except Exception as e:
            logger.warning("ChkLctreCntntsView error: %s", e)

        if keepalive_elapsed >= 600:
            _keepalive(klas, student_id)
            keepalive_elapsed = 0


def _run(klas: KLASService, lectures: list[dict], student_id: str) -> None:
    s = _ensure_status(student_id)
    for lecture in lectures:
        try:
            _watch_single(klas, lecture, student_id)
            s.completed.append(lecture["title"])
        except Exception as e:
            logger.error("Failed: %s — %s", lecture.get("title"), e)
            s.failed.append(lecture.get("title", "unknown"))

    s.running = False
    s.in_progress = None
    s.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("Watch session complete.")


# ── Public API ────────────────────────────────────────────────────────────────

def get_unwatched(klas: KLASService, year: int, semester: str) -> list[dict]:
    timetable = klas.get_timetable(year, semester)
    courses = klas.parse_timetable(timetable)
    unwatched = []
    for subject_code in courses:
        try:
            items = klas.get_recorded_lectures(subject_code, year, semester)
        except Exception:
            continue
        for item in items:
            prog = item.get("prog")
            if prog is not None and prog < 100 and item.get("starting") and item.get("oid"):
                unwatched.append(enrich_item(item))
    return unwatched


def start_watch_background(klas: KLASService, lectures: list[dict], student_id: str, password: str = "") -> None:
    """Spawn a daemon thread that drives the KLAS HTTP progress-tracking loop.

    `password` is accepted for API compat but no longer used — the existing
    KLASService requests.Session already carries the auth cookies.
    """
    _reset(lectures, student_id)
    t = threading.Thread(target=_run, args=(klas, lectures, student_id), daemon=True)
    t.start()
