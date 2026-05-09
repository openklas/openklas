from pydantic import BaseModel, field_validator
from uuid import UUID
from datetime import datetime
from typing import Literal, Optional


class UserBase(BaseModel):
    student_id: str
    role: str


class UserResponse(UserBase):
    id: UUID
    name: Optional[str] = None
    room_no: Optional[str] = None
    nickname: Optional[str] = None
    dept_name: Optional[str] = None
    work_category: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UserMe(BaseModel):
    id: UUID
    student_id: str
    name: Optional[str] = None
    room_no: Optional[str] = None
    nickname: Optional[str] = None
    dept_name: Optional[str] = None
    work_category: Optional[str] = None
    role: str
    status: str

    class Config:
        from_attributes = True


class UserProfileUpdate(BaseModel):
    """Schema for updating current user's profile (room, nickname, dept, work category)"""
    room_no: Optional[str] = None
    nickname: Optional[str] = None
    dept_name: Optional[str] = None
    work_category: Optional[str] = None


class UserRoleUpdate(BaseModel):
    """Schema for updating a user's role"""
    role: Literal["admin", "worker"]
    
    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ["admin", "worker"]:
            raise ValueError("Role must be 'admin' or 'worker'")
        return v

