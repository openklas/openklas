"""Homework schemas"""
from pydantic import BaseModel, Field
from typing import List, Optional


class HomeworkItem(BaseModel):
    task_no: int = Field(..., alias="taskNo")
    title: str = Field(..., alias="title")
    start_date: Optional[str] = Field(None, alias="startdate")
    expire_date: Optional[str] = Field(None, alias="expiredate")
    restart_date: Optional[str] = Field(None, alias="restartdate")
    reexpire_date: Optional[str] = Field(None, alias="reexpiredate")
    submit_yn: str = Field(..., alias="submityn")

    model_config = {"populate_by_name": True}


class HomeworkResponse(BaseModel):
    success: bool
    subject_code: str
    items: List[HomeworkItem] = Field(default_factory=list)
    message: Optional[str] = None


class CourseHomework(BaseModel):
    course_code: str
    course_title: str
    items: List[HomeworkItem] = Field(default_factory=list)


class AllHomeworkResponse(BaseModel):
    success: bool
    courses: List[CourseHomework] = Field(default_factory=list)
    message: Optional[str] = None
