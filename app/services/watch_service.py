"""Background service that auto-watches KLAS recorded lectures using a headless browser."""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext, Page

from app.services.klas_service import KLASService

logger = logging.getLogger(__name__)


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


_status = WatchStatus()


def get_status() -> WatchStatus:
    return _status


def reset_status() -> None:
    _status.running = False
    _status.in_progress = None
    _status.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _reset(lectures: list[dict]) -> None:
    global _status
    _status.running = True
    _status.total = len(lectures)
    _status.completed = []
    _status.in_progress = None
    _status.pending = [lec["title"] for lec in lectures]
    _status.failed = []
    _status.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _status.finished_at = None


# ── Cookie extraction ─────────────────────────────────────────────────────────

def _get_klas_cookies(klas: KLASService) -> list[dict]:
    cookies = []
    for cookie in klas.session.cookies:
        cookies.append({
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain or ".kw.ac.kr",
            "path": cookie.path or "/",
        })
    return cookies


# ── Playback ──────────────────────────────────────────────────────────────────

async def _watch_single(page: Page, lecture: dict) -> None:
    title = lecture["title"]
    url = lecture["url"]
    total_min = lecture["total_min"]

    _status.in_progress = title
    if title in _status.pending:
        _status.pending.remove(title)

    logger.info("Watching: %s (%d min)", title, total_min)

    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    # Wait for kwcommons vc-player to fully initialize
    await page.wait_for_timeout(10000)

    # Click the kwcommons front-screen play button
    for sel in [".vc-front-screen-play-btn", ".vc-front-mixed-play-btn", ".vc-pctrl-play-pause-btn"]:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.click()
                logger.info("Clicked play: %s", sel)
                break
        except Exception:
            continue

    await page.wait_for_timeout(3000)

    await page.evaluate("""
        document.querySelectorAll('video').forEach(v => {
            v.playbackRate = 2.0;
            v.muted = true;
        });
    """)

    wait_sec = int((total_min * 60) / 2 * 1.2)
    elapsed = 0
    while elapsed < wait_sec:
        chunk = min(30, wait_sec - elapsed)
        await asyncio.sleep(chunk)
        elapsed += chunk
        try:
            await page.evaluate("""
                document.querySelectorAll('video').forEach(v => {
                    if (v.paused) v.play();
                    v.playbackRate = 2.0;
                    v.muted = true;
                });
            """)
        except Exception:
            pass
        logger.info("Progress: %s — %dm/%dm elapsed", title, elapsed // 60, wait_sec // 60)

    logger.info("Finished: %s", title)


async def _browser_login(page: Page, student_id: str, password: str) -> None:
    """Do a real KLAS login in the browser to establish all session cookies."""
    logger.info("Performing browser login for %s", student_id)
    await page.goto("https://klas.kw.ac.kr/usr/cmn/login/LoginForm.do", wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)

    await page.fill("#loginId", student_id)
    await page.fill("#loginPwd", password)

    # The login button is button.btn — KLAS JS handles RSA encryption on click
    await page.click("button.btn:has-text('로그인')")

    # Wait for redirect after successful login
    await page.wait_for_timeout(5000)
    logger.info("Browser login complete. URL: %s", page.url)


async def _run(klas: KLASService, lectures: list[dict], student_id: str, password: str) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"],
        )
        context: BrowserContext = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        # Real browser login so kwcommons.kw.ac.kr session is established
        await _browser_login(page, student_id, password)

        for lecture in lectures:
            try:
                await _watch_single(page, lecture)
                _status.completed.append(lecture["title"])
            except Exception as e:
                logger.error("Failed to watch %s: %s", lecture["title"], e)
                _status.failed.append(lecture["title"])

        await browser.close()

    _status.running = False
    _status.in_progress = None
    _status.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
            url = item.get("starting")
            if prog is not None and prog < 100 and url:
                total_min = int(item.get("totalTime") or item.get("rcognTime") or 30)
                unwatched.append({
                    "title": item.get("sbjt", "Unknown"),
                    "url": url,
                    "total_min": total_min,
                    "prog": prog,
                })
    return unwatched


def start_watch_background(klas: KLASService, lectures: list[dict], student_id: str, password: str) -> None:
    """Called by FastAPI BackgroundTasks — initializes status and runs the watcher."""
    _reset(lectures)
    asyncio.run(_run(klas, lectures, student_id, password))
