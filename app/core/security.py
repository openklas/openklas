"""
Security utilities for token generation and validation.

Session storage is delegated to `app.core.session_store`. Default backend is
in-memory; set `REDIS_URL` (and `SESSION_ENCRYPTION_KEY`) to switch to Redis
for multi-worker and restart-safe sessions.
"""
import secrets
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import settings
from .session_store import get_session_store


def create_session_token() -> str:
    """Generate a secure random session token (kept for back-compat)."""
    return secrets.token_urlsafe(settings.TOKEN_LENGTH)


def create_session(student_id: str, klas_instance: Any, password: str = "") -> str:
    """Create a session and return the token."""
    return get_session_store().create(student_id, klas_instance, password)


def get_session(token: str) -> Optional[Dict[str, Any]]:
    """Return session data by token, or None if missing/expired."""
    s = get_session_store().get(token)
    return dict(s) if s is not None else None


def delete_session(token: str) -> bool:
    """Delete a session. Returns True if it existed."""
    return get_session_store().delete(token)


def get_active_sessions_count() -> int:
    """Return active session count."""
    return get_session_store().count()


# Legacy compatibility shim: some scripts and the
# `scripts/verify_per_user_isolation.py` helper reach into `sessions` directly.
# Only the in-memory backend exposes a real dict; in Redis mode this is an
# empty placeholder (don't use it for state — use the API above).
from .session_store import InMemorySessionStore as _InMemoryStore
_store = get_session_store()
sessions: Dict[str, Dict[str, Any]] = (
    _store._sessions if isinstance(_store, _InMemoryStore) else {}  # type: ignore[attr-defined]
)


# Old Login Security
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRES_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


