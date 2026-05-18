"""Lecture progress autocomplete service.

Directly calls the KLAS viewer APIs to mark lectures complete — no browser required.

Flow per lecture:
  1. POST CertiLctreStdCheck.do  (identity check)
  2. POST LctreCntntsViewSpvPage.do  → extract lecKey from response HTML
  3. Loop every `delay` seconds:
       POST UpdateProgress.do  (reports position, returns prog %)
       POST ChkLctreCntntsView.do  (KLAS heartbeat)
       until prog ≥ 100 or lessonstatus == "passed"
  4. Every 10 min: GET klas home + POST Frame.do  (session keep-alive)

Key param mapping (spec vs lecture list fields):
  API weeklyseq   ← lecture item weekNo
  API weeklysubseq ← lecture item weeklyseq
"""
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.core.config import settings
from app.services.klas_service import KLASService

logger = logging.getLogger(__name__)

# ── KLAS viewer endpoint constants ────────────────────────────────────────────

_BASE = settings.KLAS_BASE_URL
CERTI_URL   = f"{_BASE}/std/lis/evltn/CertiLctreStdCheck.do"
VIEWER_URL  = f"{_BASE}/spv/lis/lctre/viewer/LctreCntntsViewSpvPage.do"
UPDATE_URL  = f"{_BASE}/spv/lis/lctre/viewer/UpdateProgress.do"
CHECK_URL   = f"{_BASE}/spv/lis/lctre/viewer/ChkLctreCntntsView.do"
FRAME_URL   = f"{_BASE}/std/cmn/frame/Frame.do"

_FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
_JSON_HEADERS = {"Content-Type": "application/json; charset=UTF-8"}


# ── In-memory job state ───────────────────────────────────────────────────────

@dataclass
class AutocompleteStatus:
    running: bool = False
    total: int = 0
    completed: list[str] = field(default_factory=list)
    in_progress: Optional[str] = None
    pending: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    current_prog: float = 0.0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


_status = AutocompleteStatus()


def get_autocomplete_status() -> AutocompleteStatus:
    return _status


# ── KLAS API helpers ──────────────────────────────────────────────────────────

def _certi_check(klas: KLASService, grcode: str, subj: str, year: str,
                 hakgi: str, week_no: int) -> dict:
    """POST CertiLctreStdCheck.do — identity/cert check before viewing."""
    try:
        resp = klas.session.post(
            CERTI_URL,
            json={
                "title": "온라인 강의 컨텐츠 학습 인증",
                "selectYearhakgi": None,
                "selectSubj": None,
                "displayCertiPopup": False,
                "certiGubun": "",
                "birth": "",
                "password": "",
                "grcode": grcode,
                "subj": subj,
                "year": year,
                "hakgi": hakgi,
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
            },
            headers=_JSON_HEADERS,
            timeout=15,
        )
        return resp.json() if resp.ok else {}
    except Exception as e:
        logger.warning("CertiCheck failed (non-fatal): %s", e)
        return {}


def _open_viewer(klas: KLASService, p: dict, total_time: int, prog: int) -> Optional[str]:
    """POST viewer page → parse lecKey from HTML. Returns lecKey or None."""
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
        "weeklyseq":    p["weeklyseq"],    # weekNo
        "weeklysubseq": p["weeklysubseq"], # weeklyseq
        "totalTime":    str(total_time),
        "prog":         str(prog),
        "profYN":       "N",
        "previewYN":    "N",
        "late":         "N",
    }
    try:
        resp = klas.session.post(VIEWER_URL, data=form, headers=_FORM_HEADERS, timeout=20)
        html = resp.text

        # Try multiple patterns — KLAS embeds lecKey in JS or hidden inputs
        patterns = [
            r'["\']?lecKey["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            r'var\s+lecKey\s*=\s*["\']([^"\']+)["\']',
            r'name=["\']lecKey["\']\s+value=["\']([^"\']+)["\']',
            r'lecKey["\s]*[=:]["\s]*([^\s"\'&;,\]]+)',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                key = m.group(1).strip()
                logger.info("Extracted lecKey (len=%d)", len(key))
                return key

        logger.warning("lecKey not found in viewer HTML (%d bytes)", len(html))
        return None

    except Exception as e:
        logger.error("Failed to open viewer: %s", e)
        return None


def _update_progress(klas: KLASService, p: dict, lec_key: str,
                     ptime: int, is_endfile: bool) -> dict:
    """POST UpdateProgress.do — returns {diff, totalTime, lessonstatus, ptime, prog}."""
    form = {
        "year":         p["year"],
        "subj":         p["subj"],
        "bunban":       p["bunban"],
        "hakgi":        p["hakgi"],
        "module":       p["module"],
        "lesson":       p["lesson"],
        "oid":          p["oid"],
        "weeklyseq":    p["weeklyseq"],
        "weeklysubseq": p["weeklysubseq"],
        "grcode":       p["grcode"],
        "lecKey":       lec_key,
        "isendfile":    "Y" if is_endfile else "N",
    }
    try:
        resp = klas.session.post(UPDATE_URL, data=form, headers=_FORM_HEADERS, timeout=15)
        return resp.json() if resp.ok else {}
    except Exception as e:
        logger.warning("UpdateProgress failed: %s", e)
        return {}


def _check_view(klas: KLASService, p: dict, lec_key: str,
                ptime: int, is_endfile: bool) -> None:
    """POST ChkLctreCntntsView.do — KLAS heartbeat, response is usually {}."""
    form = {
        "year":         p["year"],
        "subj":         p["subj"],
        "bunban":       p["bunban"],
        "hakgi":        p["hakgi"],
        "module":       p["module"],
        "lesson":       p["lesson"],
        "oid":          p["oid"],
        "weeklyseq":    p["weeklyseq"],
        "weeklysubseq": p["weeklysubseq"],
        "grcode":       p["grcode"],
        "lecKey":       lec_key,
        "isendfile":    "Y" if is_endfile else "N",
    }
    try:
        klas.session.post(CHECK_URL, data=form, headers=_FORM_HEADERS, timeout=10)
    except Exception as e:
        logger.warning("ChkLctreCntntsView failed (non-fatal): %s", e)


def _keep_alive(klas: KLASService, student_id: str) -> None:
    """Prevent KLAS session timeout: GET home + POST Frame.do."""
    try:
        klas.session.get(_BASE, timeout=10)
        klas.session.post(
            FRAME_URL,
            data={"storeId": student_id, "storeIdChecked": "checked"},
            headers=_FORM_HEADERS,
            timeout=10,
        )
        logger.debug("Keep-alive sent for %s", student_id)
    except Exception as e:
        logger.warning("Keep-alive failed (non-fatal): %s", e)


# ── Core autocomplete logic ───────────────────────────────────────────────────

def _build_params(raw: dict, year: str, semester: str) -> dict:
    """Build the common param dict used across all progress API calls."""
    # grcode: KWU fixed code; bunban: section code (raw may have it)
    grcode = raw.get("grcode") or "N000003"
    bunban = raw.get("bunban") or "01"

    return {
        "grcode":       grcode,
        "subj":         raw.get("subj", ""),
        "year":         year,
        "hakgi":        semester,
        "bunban":       bunban,
        "module":       str(raw.get("module") or ""),
        "lesson":       str(raw.get("lesson") or ""),
        "oid":          raw.get("oid", ""),
        # API uses weekNo as weeklyseq and weeklyseq as weeklysubseq
        "weeklyseq":    str(raw.get("weekNo") or 1),
        "weeklysubseq": str(raw.get("weeklyseq") or 1),
    }


def _autocomplete_single(
    klas: KLASService,
    raw: dict,
    year: str,
    semester: str,
    student_id: str,
    delay: float = 3.0,
) -> float:
    """
    Complete one lecture. Returns final prog (0-100).

    `delay` controls seconds between UpdateProgress calls.
    Lower = faster completion but higher risk of KLAS rate-limiting.
    """
    title = raw.get("sbjt", raw.get("oid", "?"))
    total_time = int(raw.get("totalTime") or raw.get("rcognTime") or 30)
    current_prog = int(raw.get("prog") or 0)

    logger.info("[autocomplete] %s — total=%dmin, current_prog=%d%%", title, total_time, current_prog)

    p = _build_params(raw, year, semester)

    # 1. Certi check (non-blocking — failure is okay)
    _certi_check(klas, p["grcode"], p["subj"], year, semester, int(p["weeklyseq"]))

    # 2. Open viewer → lecKey
    lec_key = _open_viewer(klas, p, total_time, current_prog)
    if not lec_key:
        raise RuntimeError(f"Could not extract lecKey for {title}")

    # 3. Rapid-fire UpdateProgress with increasing ptime until prog ≥ 100
    total_secs = total_time * 60
    ptime = 60          # start at 1 min mark
    step = 60           # each call advances 1 min of video position
    prog = float(current_prog)
    last_keepalive = time.time()

    while prog < 100:
        ptime = min(ptime, total_secs)
        is_end = (ptime >= total_secs)

        result = _update_progress(klas, p, lec_key, ptime, is_end)
        prog = float(result.get("prog") or prog)
        status_str = result.get("lessonstatus", "")

        _status.current_prog = prog
        logger.info("[autocomplete] %s — ptime=%ds prog=%.1f%% status=%s",
                    title, ptime, prog, status_str)

        if prog >= 100 or status_str in ("passed", "complete"):
            break

        _check_view(klas, p, lec_key, ptime, is_end)

        # Keep-alive every ~10 minutes of wall time
        if time.time() - last_keepalive >= 600:
            _keep_alive(klas, student_id)
            last_keepalive = time.time()

        ptime += step
        time.sleep(delay)

    return prog


# ── Background runner ─────────────────────────────────────────────────────────

def _run(
    klas: KLASService,
    raw_lectures: list[dict],
    year: str,
    semester: str,
    student_id: str,
    delay: float,
) -> None:
    global _status
    _status.running = True
    _status.total = len(raw_lectures)
    _status.completed = []
    _status.failed = []
    _status.pending = [r.get("sbjt", r.get("oid", "?")) for r in raw_lectures]
    _status.current_prog = 0.0
    _status.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _status.finished_at = None

    for raw in raw_lectures:
        title = raw.get("sbjt", raw.get("oid", "?"))
        _status.in_progress = title
        if title in _status.pending:
            _status.pending.remove(title)
        try:
            final_prog = _autocomplete_single(klas, raw, year, semester, student_id, delay)
            logger.info("[autocomplete] done: %s → %.1f%%", title, final_prog)
            _status.completed.append(title)
        except Exception as e:
            logger.error("[autocomplete] FAILED %s: %s", title, e)
            _status.failed.append(title)

    _status.running = False
    _status.in_progress = None
    _status.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("[autocomplete] session complete: %d done, %d failed",
                len(_status.completed), len(_status.failed))


def start_autocomplete_background(
    klas: KLASService,
    raw_lectures: list[dict],
    year: str,
    semester: str,
    student_id: str,
    delay: float = 3.0,
) -> None:
    """Entry point for FastAPI BackgroundTasks. Runs synchronously in a thread."""
    _run(klas, raw_lectures, year, semester, student_id, delay)
