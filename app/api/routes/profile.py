"""
Profile endpoints
"""
import base64
import mimetypes
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import Response
from typing import Optional

from app.schemas.profile import (
    ProfileResponse,
    ProfileData,
    ProfileSettingsResponse,
    ProfileSettingsUpdate,
)
from app.core.security import get_session
from app.services.klas_service import KLASService
from app.api.deps import get_current_user_from_klas_session, DbSession

router = APIRouter()
security = HTTPBearer(auto_error=False)


def get_klas_service(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    token: Optional[str] = Query(None, description="Session token (alternative to Authorization header)"),
) -> KLASService:
    """Dependency to get and validate KLAS service from session"""
    raw_token = token or (credentials.credentials if credentials else None)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session_data = get_session(raw_token)
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )

    return session_data['klas']


@router.get("", response_model=ProfileResponse)
async def get_profile(klas: KLASService = Depends(get_klas_service)):
    """
    Get your profile from KLAS MyNumberQrStdPage
    
    Returns profile including:
    - Name (이름)
    - Student ID (학번)
    - Major (학과명)
    - Date of birth (생년월일)
    - Gender (성별)
    - Nationality (국적)
    - Profile image (사진) - base64 encoded data URI
    
    Requires: Bearer token in Authorization header
    """
    try:
        # Fetch profile data
        profile_data = klas.get_profile()
        
        if profile_data:
            return ProfileResponse(
                success=True,
                message="Profile fetched successfully",
                profile=ProfileData(**profile_data)
            )
        else:
            return ProfileResponse(
                success=False,
                message="Could not retrieve profile information"
            )
            
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to parse profile information: {str(e)}"
        )
    except ConnectionError as e:
        raise HTTPException(
            status_code=503,
            detail=f"KLAS service unavailable: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching profile information: {str(e)}"
        )


@router.get("/image")
async def get_profile_image(klas: KLASService = Depends(get_klas_service)):
    """
    Get your profile image from KLAS
    
    Returns the profile image as binary data (JPEG/PNG)
    Content-Type: image/jpeg or image/png
    
    Requires: Bearer token in Authorization header
    """
    try:
        # Fetch profile data
        profile_data = klas.get_profile()
        
        if not profile_data or not profile_data.get('profile_image'):
            raise HTTPException(
                status_code=404,
                detail="Profile image not found"
            )
        
        # Extract base64 data from data URI
        data_uri = profile_data['profile_image']
        
        # Parse data URI: data:image/jpeg;base64,<data>
        if not data_uri.startswith('data:image/'):
            raise HTTPException(
                status_code=422,
                detail="Invalid image format"
            )
        
        # Extract mime type and base64 data with proper error handling
        try:
            parts = data_uri.split(',', 1)
            if len(parts) != 2:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid data URI format: missing comma separator"
                )
            
            header, encoded = parts
            
            # Validate that both parts exist and are not empty
            if not header or not encoded:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid data URI format: empty header or encoded data"
                )
            
            # Parse mime type from header (e.g., "data:image/jpeg;base64" -> "image/jpeg")
            header_parts = header.split(';')
            if not header_parts:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid data URI format: malformed header"
                )
            
            mime_parts = header_parts[0].split(':')
            if len(mime_parts) < 2:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid data URI format: missing mime type in header"
                )
            
            mime_type = mime_parts[1]
            
            # Validate mime type
            if not mime_type or not mime_type.startswith('image/'):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid data URI format: invalid mime type '{mime_type}'"
                )
                
        except HTTPException:
            raise
        except (ValueError, IndexError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid data URI format: {str(e)}"
            )
        
        # Decode base64
        try:
            image_data = base64.b64decode(encoded)
        except Exception:
            raise HTTPException(
                status_code=422,
                detail="Failed to decode image data"
            )
        
        # Return as binary response
        return Response(
            content=image_data,
            media_type=mime_type,
            headers={
                "Content-Disposition": "inline; filename=profile.jpg"
            }
        )
            
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to parse image: {str(e)}"
        )
    except ConnectionError as e:
        raise HTTPException(
            status_code=503,
            detail=f"KLAS service unavailable: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching profile image: {str(e)}"
        )


@router.get("/settings", response_model=ProfileSettingsResponse)
async def get_profile_settings(
    klas: KLASService = Depends(get_klas_service),
    current_user=Depends(get_current_user_from_klas_session),
):
    """
    Get combined profile settings: KLAS profile (name, student_id, major, etc.)
    plus user-editable fields (room_no, nickname, dept_name, work_category).

    Requires: Bearer token in Authorization header (KLAS session).
    """
    out = ProfileSettingsResponse(
        room_no=current_user.room_no,
        nickname=current_user.nickname,
        dept_name=current_user.dept_name,
        work_category=current_user.work_category,
    )
    try:
        profile_data = klas.get_profile()
        if profile_data:
            out.name = profile_data.get("name")
            out.student_id = profile_data.get("student_id")
            out.major = profile_data.get("major")
            out.date_of_birth = profile_data.get("date_of_birth")
            out.gender = profile_data.get("gender")
            out.nationality = profile_data.get("nationality")
            out.profile_image = profile_data.get("profile_image")
    except Exception:
        pass
    return out


@router.patch("/settings", response_model=ProfileSettingsResponse)
async def update_profile_settings(
    body: ProfileSettingsUpdate,
    db: DbSession,
    current_user=Depends(get_current_user_from_klas_session),
):
    """
    Update user-editable profile settings (room_no, nickname, dept_name, work_category).
    Omitted fields are left unchanged; send null to clear a field.

    Requires: Bearer token in Authorization header (KLAS session).
    """
    if body.room_no is not None:
        current_user.room_no = body.room_no
    if body.nickname is not None:
        current_user.nickname = body.nickname
    if body.dept_name is not None:
        current_user.dept_name = body.dept_name
    if body.work_category is not None:
        current_user.work_category = body.work_category
    await db.commit()
    await db.refresh(current_user)
    # Return combined response (KLAS + DB); KLAS fields may be stale until next GET
    return ProfileSettingsResponse(
        name=current_user.name,
        student_id=current_user.student_id,
        major=current_user.major,
        date_of_birth=current_user.date_of_birth,
        gender=current_user.gender,
        nationality=current_user.nationality,
        profile_image=current_user.profile_image,
        room_no=current_user.room_no,
        nickname=current_user.nickname,
        dept_name=current_user.dept_name,
        work_category=current_user.work_category,
    )

