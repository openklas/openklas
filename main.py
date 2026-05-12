"""
KLAS API - Main application entry point
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_mcp import FastApiMCP

from app.core.config import settings
from app.api.routes import auth, profile, timetable, homework, lectures

# Create FastAPI app
app = FastAPI(
    title="OpenKLAS API",
    description="API for KLAS integration",
    version="1.0.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(profile.router, prefix="/api/profile", tags=["Profile"])
app.include_router(timetable.router, prefix="/api/timetable", tags=["Timetable"])
app.include_router(homework.router, prefix="/api/homework", tags=["Homework"])
app.include_router(lectures.router, prefix="/api/lectures", tags=["Lectures"])

# Mount MCP server — exclude legacy endpoints to avoid confusion
mcp = FastApiMCP(
    app,
    exclude_operations=[
        "login_api_auth_login__post",   # old /login_ (username-based)
        "logout_api_auth_logout__post", # old /logout_
    ],
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
