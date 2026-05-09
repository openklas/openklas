"""Profile schemas"""
from pydantic import BaseModel, Field
from typing import Optional


class ProfileData(BaseModel):
    """Profile data schema from MyNumberQrStdPage"""
    name: str = Field(..., description="Student name (이름)")
    student_id: str = Field(..., description="Student ID (학번)")
    major: Optional[str] = Field(None, description="Major/Department (학과명)")
    date_of_birth: Optional[str] = Field(None, description="Date of birth (생년월일)")
    gender: Optional[str] = Field(None, description="Gender (성별)")
    nationality: Optional[str] = Field(None, description="Nationality (국적)")
    profile_image: Optional[str] = Field(None, description="Profile image as base64 data URI (사진)")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "홍길동",
                    "student_id": "2022000000",
                    "major": "소프트웨어학부",
                    "date_of_birth": "2001.01.01",
                    "gender": "남성",
                    "nationality": "대한민국",
                    "profile_image": "data:image/jpeg;base64,/9j/4AAQSkZJRg..."
                }
            ]
        }
    }


class ProfileResponse(BaseModel):
    """Profile response schema"""
    success: bool = Field(..., description="Whether the request was successful")
    message: Optional[str] = Field(None, description="Response message")
    profile: Optional[ProfileData] = Field(None, description="Profile data if successful")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "message": "Profile fetched successfully",
                    "profile": {
                        "name": "홍길동",
                        "student_id": "2022000000",
                        "major": "소프트웨어학부",
                        "date_of_birth": "2001.01.01",
                        "gender": "남성",
                        "nationality": "대한민국",
                    }
                }
            ]
        }
    }


class ProfileSettingsResponse(BaseModel):
    """Combined profile: KLAS profile data + user-editable settings from DB"""
    # From KLAS /profile
    name: Optional[str] = Field(None, description="Student name (이름)")
    student_id: Optional[str] = Field(None, description="Student ID (학번)")
    major: Optional[str] = Field(None, description="Major/Department (학과명)")
    date_of_birth: Optional[str] = Field(None, description="Date of birth (생년월일)")
    gender: Optional[str] = Field(None, description="Gender (성별)")
    nationality: Optional[str] = Field(None, description="Nationality (국적)")
    profile_image: Optional[str] = Field(None, description="Profile image as base64 data URI (사진)")
    # User-editable from DB
    room_no: Optional[str] = Field(None, description="Room number")
    nickname: Optional[str] = Field(None, description="Nickname")
    dept_name: Optional[str] = Field(None, description="Department name")
    work_category: Optional[str] = Field(None, description="Work category")


class ProfileSettingsUpdate(BaseModel):
    """Body for updating profile settings (user-editable fields only)"""
    room_no: Optional[str] = None
    nickname: Optional[str] = None
    dept_name: Optional[str] = None
    work_category: Optional[str] = None

