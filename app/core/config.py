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

    # Environment — controls CORS, debug behavior, etc. Set ENV=prod in production .env.
    ENV: str = "dev"

    # CORS — production origins only. Dev localhost origins are appended automatically
    # when ENV != "prod" (see `cors_origins` property below).
    BACKEND_CORS_ORIGINS: List[str] = [
        "https://fittable-frontend.vercel.app",
        "https://fittable.vercel.app",
    ]

    @property
    def cors_origins(self) -> List[str]:
        """Effective CORS allowlist. Adds localhost dev origins when ENV != 'prod'."""
        if self.ENV.lower() == "prod":
            return self.BACKEND_CORS_ORIGINS
        return self.BACKEND_CORS_ORIGINS + [
            "http://localhost:3000",
            "http://localhost:3001",
            "http://localhost:8000",
            "http://localhost:8001",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
            "http://127.0.0.1:8000",
            "http://127.0.0.1:8001",
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
    KLAS_HW_URL: str
    KLAS_HW_VIEW_URL: str
    KLAS_FILE_LIST_URL: str
    KLAS_LECTURE_URL: str
    KLAS_RECORDED_LECTURE_URL: str
    KLAS_COURSE_INFO_URL: str
    KLAS_TEAM_PROJECT_URL: str
    KLAS_PROFILE_URL: str
    KLAS_STUDENT_INFO_URL: str
    KLAS_STUDENT_INFO_API_URL: str 
    # KLAS_GRADUATION_URL: str

    # Anthropic
    ANTHROPIC_API_KEY: str

    # Groq (used for Whisper transcription in lecture summarizer)
    GROQ_API_KEY: str

    # Voyage AI (embeddings for RAG)
    VOYAGE_API_KEY: str

    # Obsidian vault path (optional). When unset, save_to_obsidian is a no-op:
    # transcripts and summaries are still returned in API responses, just not
    # mirrored to the local filesystem. Required only on machines that host a
    # personal Obsidian vault — leave unset on the container / cloud deployment.
    OBSIDIAN_COURSES_PATH: str | None = None

    # Session Settings
    SESSION_EXPIRE_HOURS: int = 24
    TOKEN_LENGTH: int = 32

    # Redis-backed session store (optional — falls back to in-memory dict when unset).
    # Use `redis://host:port/db` (default port 6379, default db 0).
    REDIS_URL: str | None = None
    # Fernet key (base64 url-safe, 32 raw bytes). Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Required when REDIS_URL is set — used to encrypt KLAS passwords at rest.
    SESSION_ENCRYPTION_KEY: str | None = None
    # Fernet key for encrypting OAuth credentials stored in the DB.
    # Falls back to SESSION_ENCRYPTION_KEY if unset. At least one must be set
    # when using the OAuth connector flow.
    OAUTH_ENCRYPTION_KEY: str | None = None

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

