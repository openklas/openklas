"""Timetable schemas"""
from pydantic import BaseModel, Field
from typing import List, Dict, Optional


class Schedule(BaseModel):
    """Schedule information for a course"""
    day: str = Field(..., description="Day of the week")
    day_num: int = Field(..., description="Day number (0=Monday, 5=Saturday)")
    start_time: str = Field(..., description="Start time (HH:MM)")
    end_time: str = Field(..., description="End time (HH:MM)")
    location: str = Field(..., description="Location/classroom")
    professor: str = Field(..., description="Professor name")


class Course(BaseModel):
    """Course information"""
    course_title: str = Field(..., description="Course title")
    course_code: str = Field(..., description="Course code")
    schedules: List[Schedule] = Field(..., description="List of class schedules")


class TimetableResponse(BaseModel):
    """Timetable response schema"""
    success: bool = Field(..., description="Whether request was successful")
    courses: Optional[Dict[str, Course]] = Field(None, description="Dictionary of courses")
    message: Optional[str] = Field(None, description="Error message if failed")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "courses": {
                        "U20252176510300013": {
                            "course_title": "프로그래밍이론",
                            "course_code": "U20252176510300013",
                            "schedules": [
                                {
                                    "day": "Monday",
                                    "day_num": 0,
                                    "start_time": "08:00",
                                    "end_time": "10:15",
                                    "location": "새빛102",
                                    "professor": "최영근"
                                }
                            ]
                        }
                    }
                }
            ]
        }
    }

