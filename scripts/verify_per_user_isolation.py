"""
One-shot verification: prove that two authenticated users see ONLY their own
pipeline state, end-to-end through the FastAPI HTTP layer.

This bypasses real KLAS login by directly inserting fake sessions into the
in-memory session store. Run it locally; it doesn't touch the dev server.

Usage:
    uv run python scripts/verify_per_user_isolation.py
"""
import sys
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

# Import app and session store from the actual codebase
sys.path.insert(0, ".")
from main import app
from app.core.security import sessions as _sessions
from app.services.watch_service import _statuses as watch_statuses, WatchStatus
from app.services.summarize_service import _statuses as summarize_statuses, SummarizeStatus
from app.services.progress_service import _statuses as autocomplete_statuses, AutocompleteStatus


def _fake_session(student_id: str) -> dict:
    from datetime import datetime, timedelta
    klas = MagicMock()
    klas.get_current_year_semester.return_value = (2026, "1")
    return {
        "klas": klas,
        "student_id": student_id,
        "password": "fake",
        "expires_at": datetime.now() + timedelta(hours=1),
    }


def main() -> int:
    # ── Setup ────────────────────────────────────────────────────────────────
    _sessions.clear()
    watch_statuses.clear()
    summarize_statuses.clear()
    autocomplete_statuses.clear()

    _sessions["token-alice"] = _fake_session("alice123")
    _sessions["token-bob"] = _fake_session("bob456")

    # Pre-populate divergent pipeline state for both users
    sa_w = WatchStatus()
    sa_w.running = True
    sa_w.in_progress = "Alice's lecture A1"
    sa_w.pending = ["A2", "A3"]
    watch_statuses["alice123"] = sa_w

    sb_w = WatchStatus()
    sb_w.running = False
    sb_w.in_progress = "Bob's lecture B1"
    sb_w.pending = ["B2"]
    watch_statuses["bob456"] = sb_w

    sa_s = SummarizeStatus()
    sa_s.running = True
    sa_s.title = "Alice's summarize job"
    sa_s.step = "transcribing"
    summarize_statuses["alice123"] = sa_s

    sb_s = SummarizeStatus()
    sb_s.title = "Bob's summarize job"
    sb_s.step = "done"
    summarize_statuses["bob456"] = sb_s

    sa_a = AutocompleteStatus()
    sa_a.running = True
    sa_a.in_progress = "Alice's autocomplete lecture"
    sa_a.current_prog = 42.0
    autocomplete_statuses["alice123"] = sa_a

    sb_a = AutocompleteStatus()
    sb_a.in_progress = "Bob's autocomplete lecture"
    sb_a.current_prog = 99.5
    autocomplete_statuses["bob456"] = sb_a

    # ── Run the assertions ───────────────────────────────────────────────────
    client = TestClient(app)
    alice = {"Authorization": "Bearer token-alice"}
    bob = {"Authorization": "Bearer token-bob"}

    failures: list[str] = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        marker = "✓" if cond else "✗"
        print(f"  {marker} {label}" + (f"  ({detail})" if detail else ""))
        if not cond:
            failures.append(label)

    print("Watch status:")
    a = client.get("/api/recorded-lectures/watch/status", headers=alice).json()
    b = client.get("/api/recorded-lectures/watch/status", headers=bob).json()
    check("alice sees her own in_progress", a["in_progress"] == "Alice's lecture A1", a["in_progress"])
    check("bob sees his own in_progress", b["in_progress"] == "Bob's lecture B1", b["in_progress"])
    check("alice does NOT see bob's pending", "B2" not in a["pending"])
    check("bob does NOT see alice's pending", "A2" not in b["pending"] and "A3" not in b["pending"])
    check("running flags are independent", a["running"] is True and b["running"] is False)

    print("\nSummarize status:")
    a = client.get("/api/recorded-lectures/summarize/status", headers=alice).json()
    b = client.get("/api/recorded-lectures/summarize/status", headers=bob).json()
    check("alice sees her own title", a["title"] == "Alice's summarize job", a["title"])
    check("bob sees his own title", b["title"] == "Bob's summarize job", b["title"])
    check("alice's step is 'transcribing', bob's is 'done'", a["step"] == "transcribing" and b["step"] == "done")

    print("\nAutocomplete status:")
    a = client.get("/api/recorded-lectures/autocomplete/status", headers=alice).json()
    b = client.get("/api/recorded-lectures/autocomplete/status", headers=bob).json()
    check("alice sees her own current_prog", a["current_prog"] == 42.0, str(a["current_prog"]))
    check("bob sees his own current_prog", b["current_prog"] == 99.5, str(b["current_prog"]))
    check("in_progress lectures are isolated", a["in_progress"] != b["in_progress"])

    print("\nUnknown / unauthenticated:")
    code = client.get("/api/recorded-lectures/watch/status").status_code
    check("no auth → 401", code == 401, str(code))
    code = client.get("/api/recorded-lectures/watch/status", headers={"Authorization": "Bearer nope"}).status_code
    check("bad token → 401", code == 401, str(code))

    print()
    if failures:
        print(f"❌ {len(failures)} assertion(s) failed:")
        for f in failures:
            print(f"   - {f}")
        return 1
    print("✅ All isolation checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
