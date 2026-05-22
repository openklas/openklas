"""Recorded lecture video summarization pipeline.

Pipeline:
  starting URL → extract code → download MP4 (via Playwright session)
  → transcribe (faster-whisper) → summarize (Claude) → save to Obsidian
"""
import asyncio
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from anthropic import Anthropic
from playwright.async_api import async_playwright

from app.core.config import settings

logger = logging.getLogger(__name__)

KWCOMMONS_BASE = "https://kwcommons.kw.ac.kr"
OBSIDIAN_COURSES_PATH = "/Users/universe/Documents/Obsidian Vault/klas-user/semester/8/courses"


# ── In-memory job state ───────────────────────────────────────────────────────

@dataclass
class SummarizeStatus:
    running: bool = False
    oid: Optional[str] = None
    title: Optional[str] = None
    step: str = ""          # downloading | transcribing | summarizing | saving | done | error
    transcript: Optional[str] = None
    summary: Optional[str] = None
    obsidian_path: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


_statuses: dict[str, SummarizeStatus] = {}


def get_summarize_status(student_id: str) -> SummarizeStatus:
    """Return the per-user summarize status, or a fresh empty one if no job has run."""
    return _statuses.get(student_id) or SummarizeStatus()


def _ensure_status(student_id: str) -> SummarizeStatus:
    s = _statuses.get(student_id)
    if s is None:
        s = SummarizeStatus()
        _statuses[student_id] = s
    return s


# ── URL helpers ───────────────────────────────────────────────────────────────

def extract_code(starting_url: str) -> Optional[str]:
    """Extract content code from kwcommons player URL like .../em/<code>."""
    m = re.search(r'/em/([a-zA-Z0-9]+)', starting_url)
    return m.group(1) if m else None


def _mp4_candidates(code: str) -> list[str]:
    return [
        f"{KWCOMMONS_BASE}/contents5/KW10000001/{code}/contents/media_files/screen.mp4",
        f"{KWCOMMONS_BASE}/contents5/KW10000001/{code}/contents/media_files/mobile/ssmovie.mp4",
    ]


# ── Playwright download ───────────────────────────────────────────────────────

async def _browser_login(page, student_id: str, password: str) -> None:
    await page.goto(
        "https://klas.kw.ac.kr/usr/cmn/login/LoginForm.do",
        wait_until="domcontentloaded",
    )
    await page.wait_for_timeout(2000)
    await page.fill("#loginId", student_id)
    await page.fill("#loginPwd", password)
    await page.click("button.btn:has-text('로그인')")
    await page.wait_for_timeout(5000)
    logger.info("Browser login done. Current URL: %s", page.url)


async def _download_mp4(starting_url: str, code: str, student_id: str, password: str) -> tuple[bytes, str]:
    """Return (video_bytes, url_used). Tries screen.mp4 then ssmovie.mp4."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--autoplay-policy=no-user-gesture-required"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        await _browser_login(page, student_id, password)

        # Navigate to the player page to establish kwcommons session cookies
        logger.info("Navigating to player: %s", starting_url)
        await page.goto(starting_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)

        for url in _mp4_candidates(code):
            logger.info("Trying MP4 URL: %s", url)
            try:
                resp = await page.request.get(url, timeout=180000)
                if resp.ok:
                    body = await resp.body()
                    logger.info("Downloaded %d bytes from %s", len(body), url)
                    await browser.close()
                    return body, url
                else:
                    logger.warning("HTTP %s for %s", resp.status, url)
            except Exception as e:
                logger.warning("Request failed for %s: %s", url, e)

        await browser.close()
        raise ValueError(f"Could not download MP4 for code={code} (tried both URL patterns)")


# ── Transcription ─────────────────────────────────────────────────────────────

def _extract_audio(video_path: str) -> str:
    """Extract audio from video as 16kHz mono MP3 at 32kbps via ffmpeg. Returns audio path."""
    import subprocess
    audio_path = video_path.replace(".mp4", "_audio.mp3")
    subprocess.run(
        [
            "ffmpeg", "-i", video_path,
            "-ar", "16000",   # 16kHz sample rate — Whisper's native rate
            "-ac", "1",       # mono
            "-b:a", "32k",    # 32kbps keeps files tiny (< 7MB for 30min)
            audio_path, "-y",
        ],
        check=True,
        capture_output=True,
    )
    return audio_path


def _transcribe(video_path: str) -> str:
    """Extract audio and transcribe via Groq Whisper API (whisper-large-v3-turbo)."""
    from groq import Groq

    audio_path = _extract_audio(video_path)
    try:
        client = Groq(api_key=settings.GROQ_API_KEY)
        with open(audio_path, "rb") as f:
            resp = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), f),
                model="whisper-large-v3-turbo",
                language="ko",
                response_format="text",
            )
        return (resp if isinstance(resp, str) else resp.text).strip()
    finally:
        if os.path.exists(audio_path):
            os.unlink(audio_path)


# ── Summarization ─────────────────────────────────────────────────────────────

def _summarize(transcript: str, lecture_title: str, course_title: str) -> str:
    """Summarize transcript with Claude."""
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": (
                    f"You are summarizing a recorded lecture for a Korean university student.\n\n"
                    f"**Course:** {course_title}\n"
                    f"**Lecture:** {lecture_title}\n\n"
                    f"**Transcript:**\n{transcript}\n\n"
                    "Please provide a structured summary in Markdown with:\n"
                    "## Summary\n"
                    "- 3–5 concise bullet points covering the main points\n\n"
                    "## Key Concepts\n"
                    "- Important terms, definitions, or ideas\n\n"
                    "## Formulas & Definitions\n"
                    "- Any mathematical expressions or precise definitions (if applicable)\n\n"
                    "Write in English. Be concise but complete."
                ),
            }
        ],
    )
    return response.content[0].text


# ── Obsidian save ─────────────────────────────────────────────────────────────

def _sanitize(name: str, max_len: int = 60) -> str:
    """Remove filesystem-unsafe chars, strip leading dots (no `..` traversal), trim."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name).strip().lstrip('.')
    if not cleaned:
        raise ValueError(f"Name reduces to empty after sanitization: {name!r}")
    return cleaned[:max_len]


def save_to_obsidian(
    summary: str,
    transcript: str,
    course_title: str,
    lecture_title: str,
    week_no: Optional[int] = None,
) -> str:
    """Write a Markdown note to the Obsidian klas-user vault. Returns the file path."""
    vault_root = Path(OBSIDIAN_COURSES_PATH).resolve()
    course_dir = (vault_root / _sanitize(course_title)).resolve()
    lectures_dir = (course_dir / "lectures").resolve()

    if not lectures_dir.is_relative_to(vault_root):
        raise ValueError(
            f"Refusing to write outside vault root: {lectures_dir} not under {vault_root}"
        )
    lectures_dir.mkdir(parents=True, exist_ok=True)

    prefix = f"W{week_no:02d}-" if week_no is not None else ""
    filename = f"{prefix}{_sanitize(lecture_title)}.md"
    filepath = (lectures_dir / filename).resolve()

    if not filepath.is_relative_to(vault_root):
        raise ValueError(
            f"Refusing to write outside vault root: {filepath} not under {vault_root}"
        )

    note = (
        f"# {lecture_title}\n\n"
        f"> **Course:** {course_title}  \n"
        f"> **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"{summary}\n\n"
        "---\n\n"
        "## Full Transcript\n\n"
        f"{transcript}\n"
    )
    filepath.write_text(note, encoding="utf-8")
    logger.info("Saved Obsidian note: %s", filepath)
    return str(filepath)


# ── Pipeline orchestration ────────────────────────────────────────────────────

async def _run_pipeline(
    starting_url: str,
    oid: str,
    lecture_title: str,
    course_title: str,
    week_no: Optional[int],
    student_id: str,
    password: str,
) -> None:
    s = _ensure_status(student_id)
    s.running = True
    s.oid = oid
    s.title = lecture_title
    s.error = None
    s.transcript = None
    s.summary = None
    s.obsidian_path = None
    s.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    s.finished_at = None

    tmp_path: Optional[str] = None
    try:
        code = extract_code(starting_url)
        if not code:
            raise ValueError(f"Cannot extract code from URL: {starting_url}")

        # 1. Download
        s.step = "downloading"
        video_bytes, mp4_url = await _download_mp4(starting_url, code, student_id, password)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name
        logger.info("Saved temp video: %s (%d bytes)", tmp_path, len(video_bytes))

        # 2. Transcribe
        s.step = "transcribing"
        transcript = _transcribe(tmp_path)
        s.transcript = transcript
        logger.info("Transcript length: %d chars", len(transcript))

        # 3. Summarize
        s.step = "summarizing"
        summary = _summarize(transcript, lecture_title, course_title)
        s.summary = summary

        # 4. Save to Obsidian
        s.step = "saving"
        obsidian_path = save_to_obsidian(summary, transcript, course_title, lecture_title, week_no)
        s.obsidian_path = obsidian_path

        s.step = "done"

    except Exception as e:
        logger.error("Summarize pipeline error: %s", e, exc_info=True)
        s.error = str(e)
        s.step = "error"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        s.running = False
        s.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def start_summarize_background(
    starting_url: str,
    oid: str,
    lecture_title: str,
    course_title: str,
    week_no: Optional[int],
    student_id: str,
    password: str,
) -> None:
    """Entry point for FastAPI BackgroundTasks. Runs the async pipeline synchronously."""
    asyncio.run(
        _run_pipeline(starting_url, oid, lecture_title, course_title, week_no, student_id, password)
    )


# ── Record pipeline (client-uploaded audio) ───────────────────────────────────

_record_statuses: dict[str, SummarizeStatus] = {}


def get_record_status(student_id: str) -> SummarizeStatus:
    """Return the per-user record status, or a fresh empty one if no job has run."""
    return _record_statuses.get(student_id) or SummarizeStatus()


def _ensure_record_status(student_id: str) -> SummarizeStatus:
    s = _record_statuses.get(student_id)
    if s is None:
        s = SummarizeStatus()
        _record_statuses[student_id] = s
    return s


def _transcribe_audio_bytes(audio_bytes: bytes, filename: str) -> str:
    """Send raw audio bytes to Groq Whisper. Supports webm, ogg, mp3, wav, m4a."""
    from groq import Groq
    client = Groq(api_key=settings.GROQ_API_KEY)
    resp = client.audio.transcriptions.create(
        file=(filename, audio_bytes),
        model="whisper-large-v3-turbo",
        language="ko",
        response_format="text",
    )
    return (resp if isinstance(resp, str) else resp.text).strip()


def _run_record_pipeline(
    audio_bytes: bytes,
    filename: str,
    lecture_title: str,
    course_title: str,
    week_no: Optional[int],
    student_id: str,
) -> None:
    s = _ensure_record_status(student_id)
    s.running = True
    s.oid = None
    s.title = lecture_title
    s.error = None
    s.transcript = None
    s.summary = None
    s.obsidian_path = None
    s.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    s.finished_at = None

    try:
        s.step = "transcribing"
        transcript = _transcribe_audio_bytes(audio_bytes, filename)
        s.transcript = transcript
        logger.info("Record transcript length: %d chars", len(transcript))

        s.step = "summarizing"
        summary = _summarize(transcript, lecture_title, course_title)
        s.summary = summary

        s.step = "saving"
        obsidian_path = save_to_obsidian(summary, transcript, course_title, lecture_title, week_no)
        s.obsidian_path = obsidian_path

        s.step = "done"
    except Exception as e:
        logger.error("Record pipeline error: %s", e, exc_info=True)
        s.error = str(e)
        s.step = "error"
    finally:
        s.running = False
        s.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def start_record_background(
    audio_bytes: bytes,
    filename: str,
    lecture_title: str,
    course_title: str,
    week_no: Optional[int],
    student_id: str,
) -> None:
    """Entry point for FastAPI BackgroundTasks. Runs the record pipeline synchronously."""
    _run_record_pipeline(audio_bytes, filename, lecture_title, course_title, week_no, student_id)
