"""Recorded lecture schemas"""
from pydantic import BaseModel, Field
from typing import List, Optional, Union


class RecordedLectureItem(BaseModel):
    """A single recorded (online) lecture entry from KLAS."""

    model_config = {"populate_by_name": True, "extra": "ignore"}

    # Identity
    subj: Optional[str] = None
    year: Optional[str] = None
    hakgi: Optional[str] = None
    module: Optional[str] = None
    lesson: Optional[str] = None
    oid: Optional[str] = None
    grcode: Optional[str] = None   # course group code (e.g. N000003) — needed for progress API
    bunban: Optional[str] = None   # class section (e.g. 01) — needed for progress API

    # Display
    sbjt: Optional[str] = None                                      # lesson title
    module_title: Optional[str] = Field(None, alias="moduletitle")
    week_no: Optional[int] = Field(None, alias="weekNo")
    weekly_seq: Optional[int] = Field(None, alias="weeklyseq")

    # Schedule
    start_date: Optional[str] = Field(None, alias="startDate")   # "2026-03-03 00:00"
    end_date: Optional[str] = Field(None, alias="endDate")
    lrn_pd: Optional[str] = Field(None, alias="lrnPd")           # human-readable range

    # Progress — KLAS sends these as strings ("38") or ints (50) depending on subject
    prog: Optional[float] = None                                            # 0-100, KLAS occasionally sends fractional values (e.g. 62.79)
    learn_time: Optional[Union[str, int]] = Field(None, alias="learnTime") # minutes watched
    total_time: Optional[Union[str, int]] = Field(None, alias="totalTime") # required minutes
    rcogn_time: Optional[Union[str, int]] = Field(None, alias="rcognTime") # recognised duration
    achiv_time: Optional[Union[str, int]] = Field(None, alias="achivTime") # achieved duration
    tot_rcogn_time: Optional[int] = Field(None, alias="totRcognTime")
    tot_achiv_time: Optional[int] = Field(None, alias="totAchivTime")

    # Viewing
    starting: Optional[str] = None                               # playback URL
    conn_yn: Optional[str] = Field(None, alias="connYn")
    isonoff: Optional[str] = None
    ptype: Optional[str] = None

    # First-watch timestamps
    first_edu: Optional[str] = Field(None, alias="firstEdu")
    first_end: Optional[str] = Field(None, alias="firstEnd")



class RecordedLectureListResponse(BaseModel):
    success: bool
    subject_code: str
    items: List[RecordedLectureItem] = Field(default_factory=list)
    total: int = 0
    message: Optional[str] = None


class CourseRecordedLectures(BaseModel):
    course_code: str
    course_title: str
    items: List[RecordedLectureItem] = Field(default_factory=list)


class AllRecordedLecturesResponse(BaseModel):
    success: bool
    courses: List[CourseRecordedLectures] = Field(default_factory=list)
    message: Optional[str] = None


class WatchJobResponse(BaseModel):
    success: bool
    watching: int
    lectures: List[str] = Field(default_factory=list)
    message: str
    estimated_seconds: Optional[int] = None
    status_endpoint: Optional[str] = None


class WatchStatusResponse(BaseModel):
    running: bool
    total: int
    completed: List[str] = Field(default_factory=list)
    in_progress: Optional[str] = None
    pending: List[str] = Field(default_factory=list)
    failed: List[str] = Field(default_factory=list)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class SummarizeJobResponse(BaseModel):
    success: bool
    oid: str
    title: str
    message: str
    estimated_seconds: Optional[int] = None
    status_endpoint: Optional[str] = None


class SummarizeStatusResponse(BaseModel):
    running: bool
    oid: Optional[str] = None
    title: Optional[str] = None
    step: str = ""
    transcript: Optional[str] = None
    summary: Optional[str] = None
    obsidian_path: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class RecordJobResponse(BaseModel):
    success: bool
    title: str
    message: str
    estimated_seconds: Optional[int] = None
    status_endpoint: Optional[str] = None


class RecordStatusResponse(BaseModel):
    running: bool
    title: Optional[str] = None
    step: str = ""
    transcript: Optional[str] = None
    summary: Optional[str] = None
    obsidian_path: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class AutocompleteJobResponse(BaseModel):
    success: bool
    watching: int
    lectures: List[str] = Field(default_factory=list)
    message: str
    estimated_seconds: Optional[int] = None
    status_endpoint: Optional[str] = None


class AutocompleteStatusResponse(BaseModel):
    running: bool
    total: int = 0
    completed: List[str] = Field(default_factory=list)
    in_progress: Optional[str] = None
    pending: List[str] = Field(default_factory=list)
    failed: List[str] = Field(default_factory=list)
    current_prog: float = 0.0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class CertiCheckResponse(BaseModel):
    status: bool
    otp_required: bool
    email: Optional[str] = None
    mobile: Optional[str] = None
    message: str


class CertiVerifyResponse(BaseModel):
    success: bool
    message: str


class CertiBypassResponse(BaseModel):
    """Bug-bounty PoC: OTP bypass via forced status=true."""
    real_status: bool          # what KLAS actually returned
    forced_status: bool        # always True (the manipulation)
    email: Optional[str] = None
    mobile: Optional[str] = None
    viewer_leckey_obtained: Optional[bool] = None   # None = not attempted
    viewer_auth_error: Optional[bool] = None
    viewer_snippet: Optional[str] = None
    message: str
