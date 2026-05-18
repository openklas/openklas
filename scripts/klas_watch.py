#!/usr/bin/env python3
"""
Auto-watches unwatched KLAS recorded lectures in a headless browser.
The browser plays each video at 2x speed until completion.
"""

import asyncio
import requests
import sys
from datetime import datetime

from playwright.async_api import async_playwright, Page

STUDENT_ID = "2022203510"
PASSWORD = "iampro69!"
API_BASE = "http://localhost:8000/api"


def login() -> str:
    r = requests.post(f"{API_BASE}/auth/login", json={"student_id": STUDENT_ID, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["token"]


def get_unwatched(token: str) -> list:
    r = requests.get(f"{API_BASE}/recorded-lectures/all", headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    unwatched = []
    for course in r.json().get("courses", []):
        for item in course.get("items", []):
            prog = item.get("prog")
            url = item.get("starting")
            if prog is not None and prog < 100 and url:
                total_min = int(item.get("totalTime") or item.get("rcognTime") or 30)
                unwatched.append({
                    "title": item.get("sbjt", "Unknown"),
                    "course": course["course_title"],
                    "url": url,
                    "total_min": total_min,
                    "prog": prog,
                    "deadline": item.get("endDate", "?"),
                })
    return unwatched


async def watch_lecture(page: Page, lecture: dict) -> bool:
    title = lecture["title"]
    url = lecture["url"]
    total_min = lecture["total_min"]

    print(f"\n▶ Watching: {title} ({total_min} min)")
    print(f"  URL: {url}")

    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    # Try to find and click play button
    play_selectors = [
        "button.vjs-play-control",
        "button.play-btn",
        ".play-button",
        "video",
        "[class*='play']",
    ]
    for sel in play_selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.click()
                print("  ✓ Clicked play")
                break
        except Exception:
            continue

    # Set playback speed to 2x via JS
    await page.wait_for_timeout(2000)
    try:
        await page.evaluate("""
            const videos = document.querySelectorAll('video');
            videos.forEach(v => { v.playbackRate = 2.0; });
        """)
        print("  ✓ Set 2x speed")
    except Exception:
        pass

    # Wait for video to finish (total_min / 2x speed, with 20% buffer)
    wait_seconds = int((total_min * 60) / 2 * 1.2)
    print(f"  ⏳ Waiting {wait_seconds}s (~{wait_seconds//60}min at 2x)...")

    # Poll every 30s to keep session alive and check progress
    elapsed = 0
    while elapsed < wait_seconds:
        chunk = min(30, wait_seconds - elapsed)
        await page.wait_for_timeout(chunk * 1000)
        elapsed += chunk

        # Re-apply 2x in case player reset it
        try:
            await page.evaluate("""
                const videos = document.querySelectorAll('video');
                videos.forEach(v => {
                    if (v.paused) v.play();
                    v.playbackRate = 2.0;
                });
            """)
        except Exception:
            pass

        pct = int(elapsed / wait_seconds * 100)
        print(f"  [{pct:3d}%] {elapsed//60}m elapsed", end="\r")

    print(f"\n  ✅ Done: {title}")
    return True


async def main():
    print("🔑 Logging in...")
    token = login()

    lectures = get_unwatched(token)
    if not lectures:
        print("✅ No unwatched lectures!")
        return

    print(f"\nFound {len(lectures)} unwatched lecture(s):")
    for i, lec in enumerate(lectures, 1):
        print(f"  {i}. {lec['title']} — {lec['course']} ({lec['total_min']}min, due {lec['deadline']})")

    print("\nStarting in 3s... (headless browser)")
    await asyncio.sleep(3)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        # First: do a real KLAS login so cookies are set
        print("\n🌐 Setting up KLAS session in browser...")
        await page.goto("https://klas.kw.ac.kr/usr/cmn/login/LoginForm.do", wait_until="domcontentloaded")

        for lecture in lectures:
            try:
                await watch_lecture(page, lecture)
            except Exception as e:
                print(f"  ❌ Failed: {e}")

        await browser.close()

    print(f"\n🎉 All done at {datetime.now().strftime('%H:%M')}")
    print("Check KLAS to confirm progress updated.")


if __name__ == "__main__":
    asyncio.run(main())
