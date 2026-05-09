"""Session schemas"""
from pydantic import BaseModel, Field


class SessionInfo(BaseModel):
    """Session information schema"""
    student_id: str = Field(..., description="Student ID")
    created_at: str = Field(..., description="Session creation time (ISO format)")
    expires_at: str = Field(..., description="Session expiration time (ISO format)")
    time_remaining: str = Field(..., description="Time remaining until expiration")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "student_id": "2022000000",
                    "created_at": "2026-01-01T12:00:00",
                    "expires_at": "2026-01-02T12:00:00",
                    "time_remaining": "23:59:45"
                }
            ]
        }
    }

