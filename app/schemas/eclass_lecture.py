"""EClass lecture schemas"""
from pydantic import BaseModel, Field, model_validator
from typing import List, Optional


ECLASS_VIDEO_BASE = "https://kwcommons.kw.ac.kr/contents5/KW10000001"


class EClassLectureItem(BaseModel):
    model_config = {"populate_by_name": True, "extra": "ignore"}

    grcode: Optional[str] = None
    year: Optional[str] = None
    hakgi: Optional[str] = None
    subj: Optional[str] = None
    bunban: Optional[str] = None
    serial: Optional[int] = None
    content_id: Optional[str] = Field(None, alias="contentId")
    state: Optional[str] = None
    title: Optional[str] = None
    upload_size: Optional[int] = Field(None, alias="uploadSize")
    duration: Optional[int] = None          # seconds
    regist_dt: Optional[str] = Field(None, alias="registDt")
    video_url: Optional[str] = None

    @model_validator(mode="after")
    def _set_video_url(self) -> "EClassLectureItem":
        if self.content_id and not self.video_url:
            self.video_url = (
                f"{ECLASS_VIDEO_BASE}/{self.content_id}/contents/media_files/main.mp4"
            )
        return self


class EClassLectureListResponse(BaseModel):
    success: bool
    subject_code: str
    items: List[EClassLectureItem] = Field(default_factory=list)
    total: int = 0


class CourseEClassLectures(BaseModel):
    course_code: str
    course_title: str
    items: List[EClassLectureItem] = Field(default_factory=list)


class AllEClassLecturesResponse(BaseModel):
    success: bool
    courses: List[CourseEClassLectures] = Field(default_factory=list)
