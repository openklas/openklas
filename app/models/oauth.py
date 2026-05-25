from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Long-lived token issued to the AI assistant (Claude, etc.)
    access_token: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    student_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    # Fernet-encrypted KLAS credentials for silent re-authentication
    encrypted_student_id: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_password: Mapped[str] = mapped_column(Text, nullable=False)
    # Current KLAS session token (short-lived; refreshed automatically)
    klas_session_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    klas_session_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now()
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
