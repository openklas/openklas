import logging
from datetime import datetime, timedelta
from typing import Annotated, Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.models.user import User
from app.models.oauth import OAuthToken
from app.core.security import decode_access_token, get_session, create_session
from app.core.encryption import decrypt
from uuid import UUID

logger = logging.getLogger(__name__)

security = HTTPBearer()
# Optional Bearer: used by get_current_user so OpenAPI/Swagger send the token; no error when header missing (cookie fallback)
security_bearer_optional = HTTPBearer(auto_error=False)


async def _resolve_oauth_token(token: str, db: AsyncSession) -> User | None:
    """
    Resolve a long-lived OAuth access token to a User.
    Auto-refreshes the underlying KLAS session when it expires.
    Returns None if the token is not found.
    """
    result = await db.execute(
        select(OAuthToken).where(OAuthToken.access_token == token)
    )
    record: OAuthToken | None = result.scalar_one_or_none()
    if not record:
        return None

    now = datetime.now()
    klas_session_token = record.klas_session_token
    needs_refresh = (
        not klas_session_token
        or not record.klas_session_expires_at
        or now >= record.klas_session_expires_at
    )

    if needs_refresh:
        # Silently re-login to KLAS using stored encrypted credentials
        from app.services.klas_service import KLASService
        try:
            sid = decrypt(record.encrypted_student_id)
            pw = decrypt(record.encrypted_password)
            klas = KLASService()
            if not klas.login(sid, pw):
                raise RuntimeError("KLAS re-login failed")
            klas_session_token = create_session(sid, klas, pw)
            record.klas_session_token = klas_session_token
            record.klas_session_expires_at = now + timedelta(minutes=55)
        except Exception as e:
            logger.error("OAuth session refresh failed for student %s: %s", record.student_id, e)
            return None

    record.last_used_at = now
    await db.commit()

    # Ensure the refreshed KLAS session is available to route handlers
    # by injecting it into the in-memory session store if needed.
    if not get_session(klas_session_token):
        from app.services.klas_service import KLASService
        try:
            sid = decrypt(record.encrypted_student_id)
            pw = decrypt(record.encrypted_password)
            klas = KLASService()
            klas.login(sid, pw)
            create_session(sid, klas, pw)
        except Exception as e:
            logger.error("Could not rehydrate KLAS session: %s", e)

    result2 = await db.execute(
        select(User).where(User.student_id == record.student_id)
    )
    return result2.scalar_one_or_none()


async def get_current_user_from_klas_session(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Get current user from KLAS session token or long-lived OAuth access token.
    OAuth tokens are auto-refreshed when the underlying KLAS session expires.
    """
    token = credentials.credentials

    # 1. Try existing KLAS session store (direct login flow)
    session_data = get_session(token)
    if session_data:
        student_id = session_data.get("student_id")
        if student_id:
            result = await db.execute(select(User).where(User.student_id == student_id))
            user = result.scalar_one_or_none()
            if user:
                return user

    # 2. Try OAuth access token (connector flow)
    user = await _resolve_oauth_token(token, db)
    if user:
        return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token. Please login again.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer_optional),
    db: AsyncSession = Depends(get_db),
) -> User:
    # Prefer Bearer token from Authorization header (so Swagger/OpenAPI "Authorize" sends it)
    if credentials and credentials.credentials:
        token = credentials.credentials
    else:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentUserFromKlas = Annotated[User, Depends(get_current_user_from_klas_session)]
AdminUser = Annotated[User, Depends(require_admin)]
DbSession = Annotated[AsyncSession, Depends(get_db)]

