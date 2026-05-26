"""
KLAS API - Main application entry point
"""
import logging

from typing import Optional
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi_mcp import AuthConfig, FastApiMCP
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.rate_limit import limiter
from app.api.routes import auth, profile, timetable, homework, lectures, recorded_lectures, rag, workflow, oauth

logger = logging.getLogger(__name__)

# Sentry — initialize as early as possible so any subsequent import error,
# startup failure, or request crash is captured. No-op when SENTRY_DSN is unset
# (local dev typically runs without it).
if settings.SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENVIRONMENT,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        send_default_pii=settings.SENTRY_SEND_DEFAULT_PII,
        debug=settings.SENTRY_DEBUG,
    )
    logger.info("Sentry initialized (env=%s)", settings.SENTRY_ENVIRONMENT)

# Create FastAPI app
app = FastAPI(
    title="OpenKLAS API",
    description="API for KLAS integration",
    version="1.0.0",
)

# Rate limiter (slowapi) — wires the limiter instance to the app and registers
# the 429 handler so `@limiter.limit(...)` decorators work on routes.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Configure CORS — origins depend on ENV (see config.cors_origins).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(oauth.router, tags=["OAuth"])  # no prefix — /.well-known/* and /oauth/* at root
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(profile.router, prefix="/api/profile", tags=["Profile"])
app.include_router(timetable.router, prefix="/api/timetable", tags=["Timetable"])
app.include_router(homework.router, prefix="/api/homework", tags=["Homework"])
app.include_router(lectures.router, prefix="/api/lectures", tags=["Lectures"])
app.include_router(recorded_lectures.router, prefix="/api/recorded-lectures", tags=["Recorded Lectures"])
app.include_router(rag.router, prefix="/api/rag", tags=["RAG"])
app.include_router(workflow.router, prefix="/api/workflow", tags=["Workflow"])

_mcp_bearer = HTTPBearer(auto_error=False)


async def _require_mcp_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_mcp_bearer),
):
    """Guard the /mcp endpoint — raises 401 so Claude triggers the OAuth flow."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Mount MCP server — auth guard triggers Claude's OAuth connector flow;
# OAuth and legacy login routes are excluded from the tool list.
mcp = FastApiMCP(
    app,
    exclude_operations=[
        "login_api_auth_login__post",
        "logout_api_auth_logout__post",
        "oauth_metadata",
        "register_client_oauth_register_post",
        "authorize_form_oauth_authorize_get",
        "authorize_submit_oauth_authorize_post",
        "token_exchange_oauth_token_post",
    ],
    auth_config=AuthConfig(
        dependencies=[Depends(_require_mcp_auth)],
    ),
)
mcp.mount()


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "OpenKLAS API",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "auth": "/api/auth",
            "profile": "/api/profile",
            "timetable": "/api/timetable",
            "homework": "/api/homework",
            "workflow": "/api/workflow",
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD
    )
