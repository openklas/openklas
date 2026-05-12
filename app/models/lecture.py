from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, UniqueConstraint, func, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class LectureMaterial(Base):
    __tablename__ = "lecture_materials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    board_no: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_code: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_name: Mapped[str] = mapped_column(String(200), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    semester: Mapped[str] = mapped_column(String(1), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    post_title: Mapped[str] = mapped_column(String(300), nullable=False)
    atch_file_id: Mapped[str] = mapped_column(String(100), nullable=False)
    file_sn: Mapped[int] = mapped_column(Integer, nullable=False)
    file_name: Mapped[str] = mapped_column(String(300), nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("subject_code", "atch_file_id", "file_sn", name="uq_lecture_file"),
        Index("ix_lecture_subject_code", "subject_code"),
        Index("ix_lecture_board_no", "board_no"),
    )
