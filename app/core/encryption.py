"""Fernet encryption for OAuth credentials stored at rest."""
from cryptography.fernet import Fernet
from app.core.config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    key = settings.OAUTH_ENCRYPTION_KEY or settings.SESSION_ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "No encryption key configured. Set OAUTH_ENCRYPTION_KEY (or SESSION_ENCRYPTION_KEY) "
            "in your .env. Generate with:\n"
            "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()
