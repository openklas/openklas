"""Session storage backends for KLAS Bearer tokens.

Two implementations:

- `InMemorySessionStore` — single-process dict. Default when `REDIS_URL` is unset.
  Sessions die on restart; sufficient for local dev.

- `RedisSessionStore` — durable across restarts and shared across workers. Stores
  `{student_id, encrypted_password, expires_at}` in Redis keyed by token; keeps a
  per-worker in-memory cache of live `KLASService` instances (which hold the
  KLAS `requests.Session` cookies and cannot be serialized).

  On a cache miss after worker restart, the store decrypts the password from
  Redis and transparently re-logs into KLAS to rebuild the `KLASService`. First
  request after restart adds ~3–5 s; subsequent requests hit the local cache.

Both implementations expose the same surface: `create`, `get`, `delete`, `count`.
The `Session` TypedDict is the value shape returned by `get`.
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
from datetime import datetime, timedelta
from typing import Any, Optional, Protocol, TypedDict

from app.core.config import settings

logger = logging.getLogger(__name__)


class Session(TypedDict, total=False):
    klas: Any            # live KLASService instance
    student_id: str
    password: str
    created_at: datetime
    expires_at: datetime


class SessionStore(Protocol):
    def create(self, student_id: str, klas_instance: Any, password: str) -> str: ...
    def get(self, token: str) -> Optional[Session]: ...
    def delete(self, token: str) -> bool: ...
    def count(self) -> int: ...


# ── In-memory implementation (default / dev) ─────────────────────────────────


class InMemorySessionStore:
    """Process-local dict. Loses all sessions on restart."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, student_id: str, klas_instance: Any, password: str) -> str:
        token = secrets.token_urlsafe(settings.TOKEN_LENGTH)
        self._sessions[token] = {
            "klas": klas_instance,
            "student_id": student_id,
            "password": password,
            "created_at": datetime.now(),
            "expires_at": datetime.now() + timedelta(hours=settings.SESSION_EXPIRE_HOURS),
        }
        return token

    def get(self, token: str) -> Optional[Session]:
        s = self._sessions.get(token)
        if s is None:
            return None
        if datetime.now() > s["expires_at"]:
            del self._sessions[token]
            return None
        return s

    def delete(self, token: str) -> bool:
        if token in self._sessions:
            del self._sessions[token]
            return True
        return False

    def count(self) -> int:
        now = datetime.now()
        expired = [t for t, s in self._sessions.items() if now > s["expires_at"]]
        for t in expired:
            del self._sessions[t]
        return len(self._sessions)


# ── Redis-backed implementation (prod / multi-worker) ────────────────────────


class RedisSessionStore:
    """Sessions stored in Redis; live KLASService cached per-worker in-memory.

    Redis schema (per token):
        Key:   session:{token}
        Value: JSON {student_id, encrypted_password, expires_at_iso}
        TTL:   matches expires_at
    """

    KEY_PREFIX = "session:"

    def __init__(self, redis_url: str, encryption_key: str) -> None:
        import redis as _redis  # imported lazily so the module loads without redis at all
        from cryptography.fernet import Fernet

        self._redis = _redis.Redis.from_url(redis_url, decode_responses=True)
        self._fernet = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)

        # Per-worker cache of live KLASService instances. Lock guards the dict;
        # the KLASService objects themselves are not thread-safe for KLAS calls,
        # but for our usage each request handler holds the reference briefly.
        self._klas_cache: dict[str, Any] = {}
        self._lock = threading.RLock()

        # Connection is verified on first session op (redis-py connects lazily).
        # NOT at construction — `security.py` instantiates the store at import
        # time for the legacy `sessions` compat shim, and a missing/down Redis
        # must not break app startup, only the auth flow.
        logger.info("RedisSessionStore configured for %s (connection deferred)", redis_url)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _key(self, token: str) -> str:
        return f"{self.KEY_PREFIX}{token}"

    def _encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def _decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode()).decode()

    def _rehydrate_klas(self, student_id: str, password: str) -> Any:
        """Build a fresh KLASService by re-logging into KLAS with the stored password."""
        from app.services.klas_service import KLASService
        klas = KLASService()
        if not klas.login(student_id, password):
            raise RuntimeError(f"Rehydration login failed for {student_id}")
        return klas

    # ── store API ────────────────────────────────────────────────────────────

    def create(self, student_id: str, klas_instance: Any, password: str) -> str:
        token = secrets.token_urlsafe(settings.TOKEN_LENGTH)
        expires_at = datetime.now() + timedelta(hours=settings.SESSION_EXPIRE_HOURS)
        ttl_seconds = settings.SESSION_EXPIRE_HOURS * 3600

        created_at = datetime.now()
        payload = {
            "student_id": student_id,
            "encrypted_password": self._encrypt(password),
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        self._redis.set(self._key(token), json.dumps(payload), ex=ttl_seconds)

        with self._lock:
            self._klas_cache[token] = klas_instance

        return token

    def get(self, token: str) -> Optional[Session]:
        # Cache-side check (cheap): if we have the live KLASService AND Redis still has the token,
        # return immediately.
        raw = self._redis.get(self._key(token))
        if raw is None:
            with self._lock:
                self._klas_cache.pop(token, None)
            return None

        payload = json.loads(raw)
        expires_at = datetime.fromisoformat(payload["expires_at"])
        if datetime.now() > expires_at:
            self._redis.delete(self._key(token))
            with self._lock:
                self._klas_cache.pop(token, None)
            return None

        with self._lock:
            klas = self._klas_cache.get(token)

        if klas is None:
            # Worker doesn't have the live service (cold start, restart, or different worker).
            # Rehydrate by re-logging into KLAS with the stored password.
            try:
                password = self._decrypt(payload["encrypted_password"])
                klas = self._rehydrate_klas(payload["student_id"], password)
            except Exception as e:
                logger.error("Failed to rehydrate KLAS session for token: %s", e)
                return None
            with self._lock:
                self._klas_cache[token] = klas

        created_at = datetime.fromisoformat(payload["created_at"]) if "created_at" in payload else expires_at - timedelta(hours=settings.SESSION_EXPIRE_HOURS)
        return {
            "klas": klas,
            "student_id": payload["student_id"],
            "password": self._decrypt(payload["encrypted_password"]),
            "created_at": created_at,
            "expires_at": expires_at,
        }

    def delete(self, token: str) -> bool:
        deleted = bool(self._redis.delete(self._key(token)))
        with self._lock:
            self._klas_cache.pop(token, None)
        return deleted

    def count(self) -> int:
        # Approximate: counts keys with our prefix. SCAN is non-blocking.
        return sum(1 for _ in self._redis.scan_iter(match=f"{self.KEY_PREFIX}*"))


# ── Factory ──────────────────────────────────────────────────────────────────

_singleton: SessionStore | None = None


def get_session_store() -> SessionStore:
    """Return the configured session store (lazy-singleton)."""
    global _singleton
    if _singleton is not None:
        return _singleton

    if settings.REDIS_URL:
        if not settings.SESSION_ENCRYPTION_KEY:
            raise RuntimeError(
                "REDIS_URL is set but SESSION_ENCRYPTION_KEY is not. "
                "Generate one with: python -c "
                "\"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        _singleton = RedisSessionStore(settings.REDIS_URL, settings.SESSION_ENCRYPTION_KEY)
        logger.info("Using RedisSessionStore")
    else:
        _singleton = InMemorySessionStore()
        logger.info("Using InMemorySessionStore (set REDIS_URL to switch to Redis)")

    return _singleton
