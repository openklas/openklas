from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List

class Settings(BaseSettings):
    " Application settings "

    # API Settings
    API_STR: str = "/api"
    PROJECT_NAME: str = "Fittable API"
    VERSION: str = "1.0.0"
    DESCRIPTION: str = "API for Fittable"

    # CORS Settings
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
        "http://localhost:3001",
        "http://localhost:8001",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:8001",
        "https://fittable-frontend.vercel.app",
        "https://fittable.vercel.app"
    ]

    # Database Settings
    DATABASE_URL: str

     # KLAS Settings 
    KLAS_BASE_URL: str
    KLAS_LOGIN_FORM_URL: str
    KLAS_LOGIN_SECURITY_URL: str
    KLAS_LOGIN_CONFIRM_URL: str
    KLAS_LOGIN_CAPTCHA_URL: str
    KLAS_TIMETABLE_URL: str
    KLAS_SCHEDULE_URL: str
    KLAS_PROFILE_URL: str 
    KLAS_STUDENT_INFO_URL: str
    KLAS_STUDENT_INFO_API_URL: str 
    # KLAS_GRADUATION_URL: str

    # Session Settings
    SESSION_EXPIRE_HOURS: int = 24
    TOKEN_LENGTH: int = 32

    # Old Login Security Settings (not used)
    JWT_SECRET: str
    JWT_EXPIRES_MINUTES: int = 120
    JWT_ALGORITHM: str = "HS256"

    # Server Settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = True

    # Google Calendar Settings
    GOOGLE_SERVICE_ACCOUNT_FILE: str = "g-calendar.json"
    # Google Drive folder ID for schedule sheets (optional, but recommended to avoid permission issues)
    GOOGLE_DRIVE_FOLDER_ID: str | None = None
    # Existing Google Sheet ID to write schedule data to (if set, will write to this sheet instead of creating new one)
    GOOGLE_SCHEDULE_SHEET_ID: str | None = None

    # Admin Settings
    ADMIN_STUDENT_ID: int

    # PDF (work log) – path to a .ttf with Korean support (e.g. NotoSansKR-Regular.ttf)
    PDF_FONT_PATH: str | None = None
    # Optional path to a Semibold .ttf for emphasis in PDF (e.g. NotoSansKR-SemiBold.ttf). Used for all emphasized text when set.
    PDF_FONT_SEMIBOLD_PATH: str | None = None
    # Optional path to a Bold .ttf (e.g. NotoSansKR-Bold.ttf). Used if PDF_FONT_SEMIBOLD_PATH is unset; else tried from URL or fallback.
    PDF_FONT_BOLD_PATH: str | None = None

    # Sentry
    SENTRY_DSN: str | None = None
    SENTRY_ENVIRONMENT: str = "development"
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    # Send request headers and IP for users (see Sentry data collection docs)
    SENTRY_SEND_DEFAULT_PII: bool = True
    # Set True to print Sentry SDK debug logs to stderr (e.g. send failures)
    SENTRY_DEBUG: bool = False

    class Config:
        case_sensitive = True
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    """ Get cached settings instance """ 
    return Settings()


settings = get_settings()

