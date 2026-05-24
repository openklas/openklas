"""Lecture endpoints"""
from fastapi import APIRouter, HTTPException, Depends, Query, Path
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
import io
import logging
import re
from pathlib import Path as FilePath
import anthropic as anthropic_sdk
import pdfplumber
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession
from app.core.config import settings
from app.core.security import get_session
from app.models.lecture import LectureMaterial
from app.schemas.lecture import (
    LectureListResponse, LectureMaterialItem,
    LectureSyncResponse, LectureAskResponse,
)
from app.services.klas_service import KLASService
from app.services.lecture_service import sync_all_lectures

logger = logging.getLogger(__name__)

OBSIDIAN_COURSES_PATH = settings.OBSIDIAN_COURSES_PATH


def _sanitize(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "-", name).strip().lstrip(".")
    if not cleaned:
        raise ValueError(f"Name reduces to empty after sanitization: {name!r}")
    return cleaned


def _save_to_obsidian(subject_name: str, filename: str, content: str) -> Optional[str]:
    """Write a markdown note to the Obsidian vault. Returns the file path, or
    None if `OBSIDIAN_COURSES_PATH` is unset (no-op for cloud deploys)."""
    if not OBSIDIAN_COURSES_PATH:
        logger.info("OBSIDIAN_COURSES_PATH unset — skipping Obsidian save")
        return None
    vault_root = FilePath(OBSIDIAN_COURSES_PATH).resolve()
    course_dir = (vault_root / _sanitize(subject_name) / "materials").resolve()
    if not course_dir.is_relative_to(vault_root):
        raise ValueError(f"Refusing to write outside vault root: {course_dir}")
    course_dir.mkdir(parents=True, exist_ok=True)
    note_path = (course_dir / f"{_sanitize(filename)}.md").resolve()
    if not note_path.is_relative_to(vault_root):
        raise ValueError(f"Refusing to write outside vault root: {note_path}")
    note_path.write_text(content, encoding="utf-8")
    return str(note_path)

router = APIRouter()
security = HTTPBearer(auto_error=False)


def get_klas_service(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    token: Optional[str] = Query(None, description="Session token (alternative to Authorization header)"),
) -> KLASService:
    raw_token = token or (credentials.credentials if credentials else None)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session_data = get_session(raw_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return session_data["klas"]


@router.post("/sync", response_model=LectureSyncResponse)
async def sync_lectures(
    year: Optional[int] = Query(None, description="Academic year. Defaults to current."),
    semester: Optional[str] = Query(None, description="Semester: '1' or '2'. Defaults to current."),
    klas: KLASService = Depends(get_klas_service),
    db: DbSession = None,
):
    """
    Download all lecture PDFs for all enrolled subjects, extract text, and store in DB.

    Skips files already synced. Only processes PDFs (not other file types).
    This may take a while depending on the number of lectures.

    Requires: Bearer token in Authorization header
    """
    if year is None or semester is None:
        year, semester = klas.get_current_year_semester()
    try:
        synced, skipped, failed = await sync_all_lectures(klas, db, year, semester)
        return LectureSyncResponse(
            success=True,
            synced=synced,
            skipped=skipped,
            failed=failed,
            message=f"Sync complete: {synced} new, {skipped} already up to date, {failed} failed",
        )
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync error: {str(e)}")


@router.get("", response_model=LectureListResponse)
async def list_lectures(
    year: Optional[int] = Query(None),
    semester: Optional[str] = Query(None),
    klas: KLASService = Depends(get_klas_service),
    db: DbSession = None,
):
    """
    List all stored lecture materials across all subjects.

    Requires: Bearer token in Authorization header
    """
    if year is None or semester is None:
        year, semester = klas.get_current_year_semester()
    result = await db.execute(
        select(LectureMaterial)
        .where(LectureMaterial.year == year, LectureMaterial.semester == semester)
        .order_by(LectureMaterial.subject_code, LectureMaterial.sort_order, LectureMaterial.file_sn)
    )
    items = result.scalars().all()
    return LectureListResponse(
        success=True,
        items=[LectureMaterialItem.model_validate(i) for i in items],
        total=len(items),
    )


@router.get("/{subject_code}", response_model=LectureListResponse)
async def list_lectures_for_subject(
    subject_code: str = Path(..., description="Subject code from timetable"),
    year: Optional[int] = Query(None),
    semester: Optional[str] = Query(None),
    klas: KLASService = Depends(get_klas_service),
    db: DbSession = None,
):
    """
    List stored lecture materials for one subject.

    Requires: Bearer token in Authorization header
    """
    if year is None or semester is None:
        year, semester = klas.get_current_year_semester()
    result = await db.execute(
        select(LectureMaterial)
        .where(
            LectureMaterial.subject_code == subject_code,
            LectureMaterial.year == year,
            LectureMaterial.semester == semester,
        )
        .order_by(LectureMaterial.sort_order, LectureMaterial.file_sn)
    )
    items = result.scalars().all()
    return LectureListResponse(
        success=True,
        items=[LectureMaterialItem.model_validate(i) for i in items],
        total=len(items),
    )


@router.get("/ask/{board_no}", response_model=LectureAskResponse)
async def ask_about_lecture(
    board_no: int = Path(..., description="boardNo from lecture list"),
    question: str = Query(..., description="Question to ask about this lecture"),
    klas: KLASService = Depends(get_klas_service),
    db: DbSession = None,
):
    """
    Ask Claude a question about a lecture post. Reads text from DB (no re-download).
    All PDF files from the same post are combined and cached together.

    Requires: Bearer token in Authorization header
    """
    result = await db.execute(
        select(LectureMaterial)
        .where(LectureMaterial.board_no == board_no)
        .order_by(LectureMaterial.file_sn)
    )
    materials = result.scalars().all()
    if not materials:
        raise HTTPException(status_code=404, detail="Lecture not found. Run /sync first.")

    combined_text = "\n\n---\n\n".join(
        f"[{m.file_name}]\n{m.extracted_text}" for m in materials if m.extracted_text.strip()
    )
    if not combined_text:
        raise HTTPException(status_code=422, detail="No extractable text found for this lecture.")

    post_title = materials[0].post_title
    try:
        client = anthropic_sdk.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        with client.messages.stream(
            model="claude-opus-4-7",
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system="You are a helpful academic assistant. Answer questions about lecture materials clearly and concisely based on the provided content.",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Lecture: {post_title}\n\n{combined_text}",
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": f"Question: {question}"},
                ],
            }],
        ) as stream:
            message = stream.get_final_message()

        answer = next((b.text for b in message.content if b.type == "text"), "")

        subject_name = materials[0].subject_name
        note_content = f"# {post_title}\n\n**Subject:** {subject_name}\n\n## Q: {question}\n\n{answer}\n"
        obsidian_path = _save_to_obsidian(subject_name, post_title, note_content)
        logger.info("Saved lecture Q&A to %s", obsidian_path)

        return LectureAskResponse(
            success=True,
            board_no=board_no,
            post_title=post_title,
            question=question,
            answer=answer,
        )
    except anthropic_sdk.APIError as e:
        raise HTTPException(status_code=502, detail=f"AI service error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/summarize/{subject_code}")
async def summarize_subject_lectures(
    subject_code: str = Path(..., description="Subject code from timetable"),
    year: Optional[int] = Query(None),
    semester: Optional[str] = Query(None),
    klas: KLASService = Depends(get_klas_service),
    db: DbSession = None,
):
    """
    Ask Claude to generate a full study summary for all lectures in a subject.

    Reads all stored lecture texts from DB, sends to Claude with prompt caching.
    Best used after running /sync.

    Requires: Bearer token in Authorization header
    """
    if year is None or semester is None:
        year, semester = klas.get_current_year_semester()

    result = await db.execute(
        select(LectureMaterial)
        .where(
            LectureMaterial.subject_code == subject_code,
            LectureMaterial.year == year,
            LectureMaterial.semester == semester,
        )
        .order_by(LectureMaterial.sort_order, LectureMaterial.file_sn)
    )
    materials = result.scalars().all()
    if not materials:
        raise HTTPException(status_code=404, detail="No lectures found. Run /sync first.")

    subject_name = materials[0].subject_name
    combined = "\n\n---\n\n".join(
        f"[{m.post_title} / {m.file_name}]\n{m.extracted_text}"
        for m in materials if m.extracted_text.strip()
    )
    if not combined:
        raise HTTPException(status_code=422, detail="No extractable text found.")

    try:
        client = anthropic_sdk.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        with client.messages.stream(
            model="claude-opus-4-7",
            max_tokens=8192,
            thinking={"type": "adaptive"},
            system="You are a helpful academic assistant. Create clear, well-organized study summaries from lecture materials.",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Subject: {subject_name}\n\nAll lecture materials:\n\n{combined}",
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": "Create a comprehensive study summary covering all key concepts, organized by week/topic. Include important definitions, formulas, and concepts a student should know for an exam.",
                    },
                ],
            }],
        ) as stream:
            message = stream.get_final_message()

        summary = next((b.text for b in message.content if b.type == "text"), "")

        note_content = f"# {subject_name} - Study Summary\n\n{summary}\n"
        obsidian_path = _save_to_obsidian(subject_name, "Full Summary", note_content)
        logger.info("Saved lecture summary to %s", obsidian_path)

        return {
            "success": True,
            "subject_code": subject_code,
            "subject_name": subject_name,
            "lecture_count": len(materials),
            "summary": summary,
            "obsidian_path": obsidian_path,
        }
    except anthropic_sdk.APIError as e:
        raise HTTPException(status_code=502, detail=f"AI service error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
