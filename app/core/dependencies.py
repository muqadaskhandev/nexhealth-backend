"""FastAPI dependencies for authentication and authorization."""
from __future__ import annotations

import uuid

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cookies import ACCESS_COOKIE, CSRF_COOKIE
from app.core.security import decode_access_token
from app.database import get_db
from app.models.user import User, UserRole
from app.services import auth_service, user_service

CSRF_HEADER = "x-csrf-token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

_credentials_error = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
)


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    """Resolve the authenticated user from the access-token cookie.

    Enforces CSRF (double-submit) on state-changing requests: the value of the
    non-httpOnly csrf cookie must match the X-CSRF-Token header. Because a
    cross-site attacker can trigger a request with the victim's cookies but
    cannot read the cookie value to set the header, this blocks CSRF.
    """
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise _credentials_error

    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise _credentials_error

    # CSRF check for unsafe methods.
    if request.method not in _SAFE_METHODS:
        cookie_csrf = request.cookies.get(CSRF_COOKIE)
        header_csrf = request.headers.get(CSRF_HEADER)
        if not cookie_csrf or not header_csrf or cookie_csrf != header_csrf:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF token missing or invalid",
            )

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise _credentials_error

    user = await user_service.get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise _credentials_error

    # Verify the underlying session is still live (immediate revocation on
    # logout / password change / deactivation).
    sid = payload.get("sid")
    if not sid:
        raise _credentials_error
    try:
        session_uuid = uuid.UUID(str(sid))
    except ValueError:
        raise _credentials_error
    if not await auth_service.is_session_active(db, session_uuid):
        raise _credentials_error

    # Stash the active-location claim so downstream handlers can read it.
    request.state.active_location_id = payload.get("loc")
    request.state.session_id = sid
    return user


async def require_admin(current: User = Depends(get_current_user)) -> User:
    if current.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current
