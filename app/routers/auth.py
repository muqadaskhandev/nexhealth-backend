"""Authentication routes: login, logout, refresh, me, password reset.

NOTE: this module intentionally does NOT use `from __future__ import annotations`.
slowapi's @limiter.limit wrapper causes FastAPI to resolve endpoint annotations
against slowapi's module globals; with stringized annotations that resolution
fails and request bodies are misread as query params. Keeping real annotation
objects (read via __wrapped__) avoids that.
"""
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cookies import (
    REFRESH_COOKIE,
    clear_auth_cookies,
    set_auth_cookies,
)
from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MessageOut,
    ProvidersOut,
    ResetPasswordRequest,
    SessionOut,
    UserOut,
)
from app.schemas.location import LocationOut
from app.services import auth_service, oauth, user_service
from app.services.auth_service import AuthError

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


def _client_meta(request: Request) -> Tuple[Optional[str], Optional[str]]:
    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    return ua, ip


def _apply_session(response: Response, session) -> None:
    set_auth_cookies(
        response,
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        csrf_token=session.csrf_token,
    )


@router.get("/providers", response_model=ProvidersOut)
async def sso_providers() -> ProvidersOut:
    """Tell the login page which SSO buttons to render."""
    p = oauth.enabled_providers()
    return ProvidersOut(google=p["google"], azure=p["azure"], okta=p["okta"])


@router.post("/login", response_model=UserOut)
@limiter.limit("10/minute")
async def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    try:
        user = await auth_service.authenticate_password(
            db, email=payload.email, password=payload.password
        )
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=exc.message)

    ua, ip = _client_meta(request)
    session = await auth_service.issue_session(db, user, user_agent=ua, ip_address=ip)
    await db.commit()

    _apply_session(response, session)
    return UserOut.model_validate(user)


@router.post("/refresh", response_model=MessageOut)
async def refresh(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> MessageOut:
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="No session")

    ua, ip = _client_meta(request)
    try:
        session = await auth_service.rotate_refresh_token(
            db, raw, user_agent=ua, ip_address=ip
        )
    except AuthError as exc:
        await db.commit()  # persist any family revocation
        clear_auth_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=exc.message)

    await db.commit()
    _apply_session(response, session)
    return MessageOut(message="Session refreshed")


@router.post("/logout", response_model=MessageOut)
async def logout(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> MessageOut:
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        await auth_service.revoke_refresh_token(db, raw)
        await db.commit()
    clear_auth_cookies(response)
    return MessageOut(message="Logged out")


@router.get("/me", response_model=SessionOut)
async def me(
    request: Request,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionOut:
    locations = await user_service.list_user_locations(db, current.id)

    active_id = getattr(request.state, "active_location_id", None)
    active = None
    if active_id:
        active = next((l for l in locations if str(l.id) == str(active_id)), None)
    if active is None and locations:
        active = locations[0]

    return SessionOut(
        user=UserOut.model_validate(current),
        active_location=LocationOut.model_validate(active) if active else None,
        locations=[LocationOut.model_validate(l) for l in locations],
    )


@router.post("/forgot-password", response_model=MessageOut)
@limiter.limit("5/minute")
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    """Always returns success — never reveals whether an email is registered."""
    user = await user_service.get_user_by_email(db, payload.email)
    if user is not None and user.is_active:
        raw = await auth_service.create_password_reset(db, user)
        await db.commit()
        # In production this token is emailed. We log it for local development.
        _deliver_reset_email(user.email, raw)
    return MessageOut(
        message="If an account exists for that email, a reset link has been sent."
    )


@router.post("/reset-password", response_model=MessageOut)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    try:
        await auth_service.consume_password_reset(db, payload.token, payload.new_password)
    except AuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=exc.message)
    await db.commit()
    return MessageOut(message="Password updated. Please log in.")


@router.post("/change-password", response_model=MessageOut)
async def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    from app.core import security

    if not security.verify_password(payload.current_password, current.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    current.password_hash = security.hash_password(payload.new_password)
    # Invalidate all other sessions after a password change.
    await auth_service._revoke_user_sessions(db, current.id)
    await db.commit()
    clear_auth_cookies(response)
    return MessageOut(message="Password changed. Please log in again.")


def _deliver_reset_email(email: str, token: str) -> None:
    """Placeholder for the real email integration (SES/SendGrid/etc.).

    For local development we print the reset link to the server log so the flow
    is testable without an email provider.
    """
    from app.config import settings

    link = f"{settings.frontend_url}/reset-password?token={token}"
    print(f"[password-reset] {email} -> {link}")
