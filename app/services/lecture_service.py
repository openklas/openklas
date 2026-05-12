"""Lecture sync service — downloads PDFs from KLAS and stores extracted text in DB."""
import io
from datetime import datetime, timezone
from typing import Tuple

import pdfplumber
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lecture import LectureMaterial
from app.services.klas_service import KLASService


def _extract_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n\n".join(p for p in pages if p.strip())


async def sync_all_lectures(
    klas: KLASService,
    db: AsyncSession,
    year: int,
    semester: str,
) -> Tuple[int, int, int]:
    """
    Fetch all lecture PDFs for every enrolled subject, extract text, upsert to DB.

    Returns (synced, skipped, failed) counts.
    """
    timetable_data = klas.get_timetable(year, semester)
    courses = klas.parse_timetable(timetable_data)

    synced = skipped = failed = 0

    for subject_code, course_info in courses.items():
        try:
            posts = klas.get_lecture_list(subject_code, year, semester)
        except Exception:
            failed += 1
            continue

        for post in posts:
            atch_file_id = post.get("atchFileId")
            if not atch_file_id or not post.get("fileCnt", 0):
                continue

            try:
                files = klas.get_homework_files(atch_file_id)
            except Exception:
                failed += 1
                continue

            for f in files:
                if f.get("ext", "").lower() not in ("pdf", "pptx", "ppt"):
                    continue

                file_sn = int(f.get("fileSn") or f.get("id") or 0)
                if not file_sn:
                    continue

                # Skip if already synced
                existing = await db.execute(
                    select(LectureMaterial).where(
                        LectureMaterial.subject_code == subject_code,
                        LectureMaterial.atch_file_id == atch_file_id,
                        LectureMaterial.file_sn == file_sn,
                    )
                )
                if existing.scalar_one_or_none():
                    skipped += 1
                    continue

                try:
                    pdf_bytes = klas.get_homework_file_bytes(atch_file_id, file_sn)
                    text = ""
                    if f.get("ext", "").lower() == "pdf":
                        text = _extract_text(pdf_bytes)
                except Exception:
                    failed += 1
                    continue

                db.add(LectureMaterial(
                    board_no=post.get("boardNo", 0),
                    subject_code=subject_code,
                    subject_name=course_info.get("course_title", ""),
                    year=year,
                    semester=semester,
                    sort_order=post.get("sortOrdr", 0),
                    post_title=post.get("title", ""),
                    atch_file_id=atch_file_id,
                    file_sn=file_sn,
                    file_name=f.get("fileName", ""),
                    extracted_text=text,
                    synced_at=datetime.now(timezone.utc),
                ))
                synced += 1

        await db.commit()

    return synced, skipped, failed
