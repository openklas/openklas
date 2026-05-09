"""
Security utilities for token generation and validation
"""
import secrets
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import settings


# In-memory session storage (use Redis in production)
sessions: Dict[str, Dict[str, Any]] = {}


def create_session_token() -> str:
    """Generate a secure random session token"""
    return secrets.token_urlsafe(settings.TOKEN_LENGTH)


def create_session(student_id: str, klas_instance: Any) -> str:
    """
    Create a new session and return the token
    
    Args:
        student_id: Student ID
        klas_instance: KLASService instance with authenticated session
        
    Returns:
        Session token
    """
    token = create_session_token()
    
    sessions[token] = {
        'klas': klas_instance,
        'student_id': student_id,
        'created_at': datetime.now(),
        'expires_at': datetime.now() + timedelta(hours=settings.SESSION_EXPIRE_HOURS)
    }
    
    return token


def get_session(token: str) -> Optional[Dict[str, Any]]:
    """
    Get session data by token
    
    Args:
        token: Session token
        
    Returns:
        Session data or None if not found/expired
    """
    if token not in sessions:
        return None
    
    session_data = sessions[token]
    
    # Check if expired
    if datetime.now() > session_data['expires_at']:
        del sessions[token]
        return None
    
    return session_data


def delete_session(token: str) -> bool:
    """
    Delete a session
    
    Args:
        token: Session token
        
    Returns:
        True if deleted, False if not found
    """
    if token in sessions:
        del sessions[token]
        return True
    return False


def get_active_sessions_count() -> int:
    """Get count of active sessions"""
    # Clean up expired sessions
    now = datetime.now()
    expired_tokens = [
        token for token, data in sessions.items()
        if now > data['expires_at']
    ]
    for token in expired_tokens:
        del sessions[token]
    
    return len(sessions)


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


