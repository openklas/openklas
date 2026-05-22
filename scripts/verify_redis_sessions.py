"""
Verify the Redis session store end-to-end without hitting real KLAS.

Mocks `KLASService` so the rehydrate path can be exercised offline. Confirms:
- Create → store ID in Redis, cache the live KLASService locally
- Same-worker get → cache hit returns the SAME klas object
- After cache clear (simulating worker restart) → rehydrate via stored password
- Password is encrypted at rest in Redis (not stored as plaintext)
- Delete removes from both Redis and the local cache

Prereqs:
  • Redis running locally on port 6379 (e.g. `redis-server --daemonize yes`)
  • REDIS_URL and SESSION_ENCRYPTION_KEY exported in env, OR set inline (we
    do this automatically below for the test).

Usage:
  uv run python scripts/verify_redis_sessions.py
"""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, ".")


def main() -> int:
    # Generate a fresh Fernet key for the test
    from cryptography.fernet import Fernet
    os.environ["REDIS_URL"] = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    os.environ["SESSION_ENCRYPTION_KEY"] = os.environ.get(
        "SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )

    # Bust caches so the settings + store pick up the env vars
    import app.core.config as _cfg
    _cfg.get_settings.cache_clear()
    _cfg.settings = _cfg.get_settings()
    import app.core.session_store as _ss
    _ss._singleton = None

    # Mock KLASService so the rehydrate path doesn't hit real KLAS
    import app.services.klas_service as klas_mod
    mock_cls = MagicMock()
    mock_cls.return_value.login.return_value = True
    klas_mod.KLASService = mock_cls

    from app.core.security import create_session, get_session, delete_session
    from app.core.session_store import get_session_store, RedisSessionStore

    failures: list[str] = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        marker = "✓" if cond else "✗"
        print(f"  {marker} {label}" + (f"  ({detail})" if detail else ""))
        if not cond:
            failures.append(label)

    store = get_session_store()
    check("backend is RedisSessionStore", isinstance(store, RedisSessionStore))

    # Create
    original_klas = MagicMock()
    token = create_session("studentA", original_klas, "secret-password")
    check("create returned a token", isinstance(token, str) and len(token) > 30)

    # Cache hit
    s = get_session(token)
    check("get returns same klas object on cache hit", s is not None and s["klas"] is original_klas)
    check("student_id roundtrips", s and s["student_id"] == "studentA")
    check("password roundtrips (decrypted)", s and s["password"] == "secret-password")

    # Confirm Redis stores it encrypted
    import redis as _r
    r = _r.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    raw = r.get(f"session:{token}")
    check("Redis value exists", raw is not None)
    check("password is NOT plaintext in Redis", "secret-password" not in (raw or ""))

    # Worker restart simulation
    store._klas_cache.clear()
    s2 = get_session(token)
    check("rehydrate after cache clear succeeds", s2 is not None)
    check(
        "rehydrate built a NEW KLASService (not the original)",
        s2 and s2["klas"] is not original_klas,
    )
    login_args = mock_cls.return_value.login.call_args
    check(
        "rehydrate called login() with stored creds",
        login_args is not None and login_args.args == ("studentA", "secret-password"),
        str(login_args),
    )

    # Delete
    check("delete returns True", delete_session(token))
    check("get after delete returns None", get_session(token) is None)

    # Cleanup
    r.flushdb()

    print()
    if failures:
        print(f"❌ {len(failures)} assertion(s) failed:")
        for f in failures:
            print(f"   - {f}")
        return 1
    print("✅ All Redis session checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
