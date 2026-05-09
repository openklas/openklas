"""University (academic) schedule schemas — 학사일정 from KLAS."""
from pydantic import BaseModel, Field
from typing import List, Optional


class UniversityScheduleItem(BaseModel):
    """Single university/academic schedule event (학사일정)."""

    type: Optional[str] = Field(None, description="Event type code (e.g. 90)")
    type_nm: Optional[str] = Field(None, alias="typeNm", description="Event type name (e.g. 학사일정)")
    title: Optional[str] = Field(None, description="Event title")
    started: Optional[str] = Field(None, description="Start datetime YYYYMMDDHHmm")
    ended: Optional[str] = Field(None, description="End datetime YYYYMMDDHHmm")
    schdul_dt: Optional[str] = Field(None, alias="schdulDt", description="Schedule date YYYY-MM-DD")
    schdul_title: Optional[str] = Field(None, alias="schdulTitle", description="Full schedule title with prefix")
    schdul_time: Optional[str] = Field(None, alias="schdulTime", description="Time range (e.g. 00:00~23:59)")
    schdul_color: Optional[str] = Field(None, alias="schdulColor", description="Display color hex")
    chkdate: Optional[str] = Field(None, description="Check date YYYYMMDD")
    daynum: Optional[str] = Field(None, description="Day of month")
    dayname: Optional[str] = Field(None, description="Day of week (1=Mon, 7=Sun)")

    model_config = {"populate_by_name": True}


class UniversityScheduleResponse(BaseModel):
    """Response for university schedule list."""

    success: bool = Field(..., description="Whether the request succeeded")
    start_date: Optional[str] = Field(None, description="Start date of the requested range (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="End date of the requested range (YYYY-MM-DD)")
    items: List[UniversityScheduleItem] = Field(default_factory=list, description="Schedule events")
    message: Optional[str] = Field(None, description="Error or info message")

    model_config = {"populate_by_name": True}
