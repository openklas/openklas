from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, func, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
        server_default="pending"
    )
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    major: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    date_of_birth: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    nationality: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    profile_image: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    room_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    nickname: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    dept_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    work_category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="worker", server_default="worker"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # shifts = relationship("Shift", back_populates="user", foreign_keys="Shift.user_id", cascade="all, delete-orphan")
    # created_shifts = relationship(
    #     "Shift", back_populates="creator", foreign_keys="Shift.created_by", cascade="all, delete-orphan"
    # )
    # timetable_entries = relationship(
    #     "TimetableEntry", back_populates="user", cascade="all, delete-orphan"
    # )

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'active')", name="users_status_check"),
        CheckConstraint("role IN ('admin', 'worker')", name="users_role_check"),
    )
