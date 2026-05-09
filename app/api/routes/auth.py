"""
Authentication endpoints
"""
from fastapi import APIRouter, HTTPException, Depends, status, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.services.auth_service import authenticate_user, create_user_token
from app.services.klas_service import KLASService
from app.core.config import settings
from app.core.security import create_session, delete_session, create_access_token

from app.api.deps import DbSession, CurrentUser, CurrentUserFromKlas
from app.schemas.auth import LoginRequest, LoginResponse, LoginRequest_, TokenResponse_
from app.schemas.user import UserMe
from app.models.user import User
from sqlalchemy import select

router = APIRouter()
security = HTTPBearer()


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: DbSession):
    """
    Login to KLAS and get a session token
    
    - **student_id**: Your student ID (학번)
    - **password**: Your KLAS password
    
    Returns a session token valid for 24 hours
    Automatically creates or updates user in database
    """
    try:
        # Initialize KLAS service and login
        klas = KLASService()
        success = klas.login(request.student_id, request.password)
        
        if success:
            # Fetch profile data from KLAS
            try:
                profile_data = klas.get_profile()
            except Exception as e:
                # If profile fetch fails, still allow login but with minimal data
                profile_data = {
                    'student_id': request.student_id,
                    'name': None,
                    'major': None,
                    'date_of_birth': None,
                    'gender': None,
                    'nationality': None,
                    'profile_image': None,
                }
            
            # Check if user exists in database
            result = await db.execute(
                select(User).where(User.student_id == request.student_id)
            )
            user = result.scalar_one_or_none()
            
            if user:
                # Update existing user with latest profile data
                user.name = profile_data.get('name') or user.name
                user.major = profile_data.get('major') or user.major
                user.date_of_birth = profile_data.get('date_of_birth') or user.date_of_birth
                user.gender = profile_data.get('gender') or user.gender
                user.nationality = profile_data.get('nationality') or user.nationality
                user.profile_image = profile_data.get('profile_image') or user.profile_image
                # Don't auto-approve - keep existing status (admin must approve)
            else:
                # Create new user
                user = User(
                    student_id=profile_data.get('student_id') or request.student_id,
                    name=profile_data.get('name'),
                    major=profile_data.get('major'),
                    date_of_birth=profile_data.get('date_of_birth'),
                    gender=profile_data.get('gender'),
                    nationality=profile_data.get('nationality'),
                    profile_image=profile_data.get('profile_image'),
                    role='worker',  # Default role, can be changed by admin
                    status='pending',  # Require admin approval before activation
                )
                db.add(user)
            
            await db.commit()
            await db.refresh(user)
            
            # Create session token (for KLAS session / auth/me)
            token = create_session(request.student_id, klas)
            # Create JWT for API routes (shifts, users, holidays)
            access_token = create_access_token(data={"sub": str(user.id)})
            
            return LoginResponse(
                success=True,
                message="Login successful",
                token=token,
                access_token=access_token,
            )
        else:
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials"
            )
            
    except ConnectionError as e:
        raise HTTPException(
            status_code=503,
            detail=f"KLAS service unavailable: {str(e)}"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Login failed: {str(e)}"
        )


@router.post("/logout")
async def logout(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Logout and invalidate session token
    
    Requires: Bearer token in Authorization header
    """
    token = credentials.credentials
    
    if delete_session(token):
        return {"success": True, "message": "Logged out successfully"}
    
    raise HTTPException(
        status_code=404,
        detail="Token not found"
    )



# Old login routes
@router.post("/login_", response_model=TokenResponse_)
async def login(request: LoginRequest_, response: Response, db: DbSession):
    user = await authenticate_user(db, request.username, request.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    access_token = create_user_token(user)

    # Set httpOnly cookie for Next.js proxy usage
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=settings.JWT_EXPIRES_MINUTES * 60,
        samesite="lax",
        secure=False,  # Set True in production with HTTPS
    )

    return TokenResponse_(access_token=access_token)


@router.post("/logout_")
async def logout(response: Response):
    response.delete_cookie(key="access_token")
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserMe)
async def get_me(current_user: CurrentUserFromKlas):
    """
    Get current user information from KLAS session
    
    Requires: Bearer token (KLAS session token) in Authorization header
    """
    return UserMe(
        id=current_user.id,
        student_id=current_user.student_id,
        name=current_user.name,
        role=current_user.role,
        status=current_user.status,
    )

