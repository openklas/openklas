from pydantic import BaseModel, Field
from typing import Optional


class LoginRequest(BaseModel):
    """Login request schema"""
    student_id: str = Field(..., description="Student ID (학번)")
    password: str = Field(..., description="KLAS password")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "student_id": "2022203510",
                    "password": "iamdumb69!"
                }
            ]
        }
    }

class LoginResponse(BaseModel):
    """Login response schema"""
    success: bool = Field(..., description="Whether login was successful")
    message: str = Field(..., description="Response message")
    token: Optional[str] = Field(..., description="Session token (KLAS session)")
    access_token: Optional[str] = Field(None, description="JWT for API auth (shifts, users, holidays)")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "message": "Login successful",
                    "token": "abc123 ...",
                    "access_token": "eyJ..."
                }
            ]
        }
    }

# Old login schemas
class LoginRequest_(BaseModel):
    username: str
    password: str


class TokenResponse_(BaseModel):
    access_token: str
    token_type: str = "bearer"

