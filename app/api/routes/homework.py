"""Homework endpoints"""
from fastapi import APIRouter, HTTPException, Depends, Query, Path
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
import io
import pdfplumber
import anthropic as anthropic_sdk
from app.core.config import settings

from app.schemas.homework import (
    HomeworkResponse, HomeworkItem,
    AllHomeworkResponse, CourseHomework,
    HomeworkDetailResponse, HomeworkDetail,
    HomeworkFilesResponse, HomeworkFile,
)
from app.core.security import get_session
from app.services.klas_service import KLASService

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


@router.get("/all", response_model=AllHomeworkResponse)
async def get_all_homework(
    year: Optional[int] = Query(None, description="Academic year. Defaults to current year."),
    semester: Optional[str] = Query(None, description="Semester: '1' or '2'. Defaults to current."),
    klas: KLASService = Depends(get_klas_service),
):
    """
    Get homework for all enrolled subjects in one call.

    Fetches the timetable to discover subject codes, then retrieves homework
    for each subject. Results are sorted most-recent-first per subject.

    Requires: Bearer token in Authorization header
    """
    try:
        if year is None or semester is None:
            year, semester = klas.get_current_year_semester()

        timetable_data = klas.get_timetable(year, semester)
        courses = klas.parse_timetable(timetable_data)

        result: list[CourseHomework] = []
        for course_code, course_info in courses.items():
            try:
                raw = klas.get_homework(course_code, year, semester)
                items = [HomeworkItem.model_validate(item) for item in raw]
            except Exception:
                items = []
            result.append(CourseHomework(
                course_code=course_code,
                course_title=course_info["course_title"],
                items=items,
            ))

        return AllHomeworkResponse(success=True, courses=result)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching homework: {str(e)}")


@router.get("/detail", response_model=HomeworkDetailResponse)
async def get_homework_detail(
    subject_code: str = Query(..., description="Subject code from timetable"),
    ordseq: int = Query(..., description="ordseq from homework list"),
    weekly_seq: int = Query(..., description="weeklyseq from homework list"),
    weekly_sub_seq: int = Query(..., description="weeklysubseq from homework list"),
    year: Optional[int] = Query(None),
    semester: Optional[str] = Query(None),
    klas: KLASService = Depends(get_klas_service),
):
    """
    Get full detail for a specific homework task, including description (HTML) and atchFileId.

    Use ordseq, weeklyseq, weeklysubseq from the homework list response.

    Requires: Bearer token in Authorization header
    """
    try:
        data = klas.get_homework_detail(subject_code, ordseq, weekly_seq, weekly_sub_seq, year, semester)
        rpt_raw = data.get("rpt")
        rpt = HomeworkDetail.model_validate(rpt_raw) if rpt_raw else None
        return HomeworkDetailResponse(success=True, rpt=rpt)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching homework detail: {str(e)}")


@router.get("/files/{attach_id}", response_model=HomeworkFilesResponse)
async def get_homework_files(
    attach_id: str,
    klas: KLASService = Depends(get_klas_service),
):
    """
    Get list of files attached to a homework task.

    Use atch_file_id from the homework detail response.

    Requires: Bearer token in Authorization header
    """
    try:
        raw = klas.get_homework_files(attach_id)
        files = [HomeworkFile.model_validate(f) for f in raw]
        return HomeworkFilesResponse(success=True, attach_id=attach_id, files=files)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching homework files: {str(e)}")


@router.get("/files/{attach_id}/{file_sn}/ask", operation_id="ask_homework_file")
async def ask_about_homework_file(
    attach_id: str = Path(..., description="atchFileId from homework detail"),
    file_sn: int = Path(..., description="fileSn from file list"),
    question: str = Query(..., description="Question to ask about the homework PDF"),
    klas: KLASService = Depends(get_klas_service),
):
    """
    Ask a question about a homework PDF using Claude AI.

    Downloads the PDF from KLAS, extracts text, and answers your question.
    Uses prompt caching so repeated questions on the same PDF are fast and cheap.

    Requires: Bearer token in Authorization header
    """
    try:
        pdf_bytes = klas.get_homework_file_bytes(attach_id, file_sn)

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        pdf_text = "\n\n".join(p for p in pages if p.strip())

        if not pdf_text:
            raise HTTPException(status_code=422, detail="Could not extract text from PDF.")

        client = anthropic_sdk.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        with client.messages.stream(
            model="claude-opus-4-7",
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system="You are a helpful academic assistant. Answer questions about homework assignments clearly and concisely based on the provided document.",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Here is the homework document:\n\n{pdf_text}",
                            "cache_control": {"type": "ephemeral"},
                        },
                        {
                            "type": "text",
                            "text": f"Question: {question}",
                        },
                    ],
                }
            ],
        ) as stream:
            message = stream.get_final_message()

        answer = next(
            (block.text for block in message.content if block.type == "text"), ""
        )
        return {"success": True, "question": question, "answer": answer}

    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS service unavailable: {str(e)}")
    except anthropic_sdk.APIError as e:
        raise HTTPException(status_code=502, detail=f"AI service error: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/files/{attach_id}/{file_sn}/download", operation_id="download_homework_file")
async def download_homework_file(
    attach_id: str = Path(..., description="atchFileId from homework detail"),
    file_sn: int = Path(..., description="fileSn from file list"),
    klas: KLASService = Depends(get_klas_service),
):
    """
    Download a file attached to a homework task.

    Use attach_id (atch_file_id) from the detail endpoint and file_sn from the files endpoint.

    Requires: Bearer token in Authorization header
    """
    try:
        content, filename, content_type = klas.download_homework_file(attach_id, file_sn)
        return StreamingResponse(
            content,
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error downloading file: {str(e)}")


@router.get("", response_model=HomeworkResponse)
async def get_homework(
    subject_code: str = Query(..., description="Subject code (e.g. U202618484I030032)"),
    year: Optional[int] = Query(None, description="Academic year (e.g. 2026). Defaults to current year."),
    semester: Optional[str] = Query(None, description="Semester: '1' for Spring, '2' for Fall. Defaults to current."),
    klas: KLASService = Depends(get_klas_service),
):
    """
    Get homework list for a subject, sorted by most recent first (highest taskNo).

    - **subject_code**: Subject code from timetable (required)
    - **year**: Academic year (optional, defaults to current)
    - **semester**: '1' or '2' (optional, defaults to current)

    Requires: Bearer token in Authorization header
    """
    try:
        raw = klas.get_homework(subject_code, year, semester)
        items = [HomeworkItem.model_validate(item) for item in raw]
        return HomeworkResponse(success=True, subject_code=subject_code, items=items)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=f"KLAS service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching homework: {str(e)}")
