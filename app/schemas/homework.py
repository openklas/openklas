"""Homework schemas"""
from pydantic import BaseModel, Field
from typing import List, Optional


class HomeworkItem(BaseModel):
    task_no: int = Field(..., alias="taskNo")
    ordseq: Optional[int] = Field(None, alias="ordseq")
    weeklyseq: Optional[int] = Field(None, alias="weeklyseq")
    weeklysubseq: Optional[int] = Field(None, alias="weeklysubseq")
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


class HomeworkDetail(BaseModel):
    ordseq: int
    weeklyseq: int
    weeklysubseq: int
    title: str
    startdate: Optional[str] = None
    expiredate: Optional[str] = None
    restartdate: Optional[str] = None
    reexpiredate: Optional[str] = None
    contents: Optional[str] = None
    submitfiletype: Optional[str] = None
    atch_file_id: Optional[str] = Field(None, alias="atchFileId")
    submit_yn: str = Field(..., alias="submityn")
    filelimit: Optional[str] = None

    model_config = {"populate_by_name": True}


class HomeworkDetailResponse(BaseModel):
    success: bool
    rpt: Optional[HomeworkDetail] = None
    message: Optional[str] = None


class HomeworkFile(BaseModel):
    file_name: str = Field(..., alias="fileName")
    ext: str
    file_size: int = Field(..., alias="fileSize")
    download: str
    created_at: str = Field(..., alias="createdAt")

    model_config = {"populate_by_name": True}


class HomeworkFilesResponse(BaseModel):
    success: bool
    attach_id: str
    files: List[HomeworkFile] = Field(default_factory=list)


class CourseHomework(BaseModel):
    course_code: str
    course_title: str
    items: List[HomeworkItem] = Field(default_factory=list)


class AllHomeworkResponse(BaseModel):
    success: bool
    courses: List[CourseHomework] = Field(default_factory=list)
    message: Optional[str] = None
