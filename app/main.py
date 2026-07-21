"""FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.routers import appointment_types, auth, invites, locations, platform, practice, staff, sso, users
from app.services.logo_storage import logos_dir

# Import models so metadata is populated (used by health check / migrations).
from app import models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast on insecure production config.
    if settings.is_production:
        settings.validate_for_production()
    logos_dir()  # ensure upload folder exists
    yield


app = FastAPI(
    title="NexHealth Backend",
    version="1.0.0",
    description="Authentication, user management, and secure sessions for NexHealth.",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url=None,
)

# Rate limiting (shared limiter used by decorated routes).
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: credentialed requests from the SPA origin(s) only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "Authorization"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok", "environment": settings.environment}


app.include_router(auth.router)
app.include_router(sso.router)
app.include_router(locations.router)
app.include_router(users.router)
app.include_router(platform.router)
app.include_router(practice.router)
app.include_router(invites.router)
app.include_router(staff.router)
app.include_router(appointment_types.router)

# Local logo uploads (dev / single-node). Production would use S3/CDN.
app.mount("/uploads", StaticFiles(directory=str(logos_dir().parent)), name="uploads")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never leak internals to the client; log server-side in a real deployment.
    if settings.debug:
        raise exc
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
