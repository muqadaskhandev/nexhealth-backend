"""Authentication routes: login, logout, refresh, me, password reset.

NOTE: this module intentionally does NOT use `from __future__ import annotations`.
slowapi's @limiter.limit wrapper causes FastAPI to resolve endpoint annotations
against slowapi's module globals; with stringized annotations that resolution
fails and request bodies are misread as query params. Keeping real annotation
objects (read via __wrapped__) avoids that.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.cookies import (
    REFRESH_COOKIE,
    clear_auth_cookies,
    set_auth_cookies,
)
from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.token import SsoTotpTransaction
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MessageOut,
    ProvidersOut,
    ResetPasswordRequest,
    SessionOut,
    TotpEnableRequest,
    TotpRequiredOut,
    TotpSetupOut,
    TotpVerifyRequest,
    UserOut,
)
from app.schemas.location import LocationOut
from app.services import auth_service, oauth, user_service, totp_service
from app.services.auth_service import AuthError


def _now() -> datetime:
    return datetime.now(timezone.utc)

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


@router.post("/login", response_model=Union[UserOut, TotpRequiredOut])
@limiter.limit("10/minute")
async def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> Union[UserOut, TotpRequiredOut]:
    try:
        user = await auth_service.authenticate_password(
            db, email=payload.email, password=payload.password
        )
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=exc.message)

    # If user has TOTP enabled, create a transaction token and return it
    if user.totp_enabled:
        ua, ip = _client_meta(request)
        raw_tx = security.generate_opaque_token()
        tx = SsoTotpTransaction(
            user_id=user.id,
            token_hash=security.hash_token(raw_tx),
            expires_at=_now() + timedelta(minutes=10),
            user_agent=(ua or "")[:400] or None,
            ip_address=(ip or "")[:64] or None,
        )
        db.add(tx)
        await db.commit()
        return TotpRequiredOut(totp_required=True, tx=raw_tx)

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


@router.post("/totp/verify", response_model=MessageOut)
async def totp_verify(
    payload: TotpVerifyRequest,
    request: Request,
    response: Response,
    tx: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    """Verify TOTP code during login 2FA flow and create session."""
    from sqlalchemy import select

    tx_token = tx
    if not tx_token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Missing transaction token")

    # Look up the transaction
    tx_hash = security.hash_token(tx_token)
    result = await db.execute(
        select(SsoTotpTransaction).where(
            SsoTotpTransaction.token_hash == tx_hash
        )
    )
    tx = result.scalar_one_or_none()

    if tx is None or tx.completed_at is not None or tx.expires_at <= _now():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid or expired transaction")

    # Get user and verify TOTP code
    user = await user_service.get_user_by_id(db, tx.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    try:
        await auth_service.ensure_practice_active(db, user)
    except AuthError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=exc.message)

    if not totp_service.verify_totp(secret=user.totp_secret or "", code=payload.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid 2FA code")

    # Mark transaction as completed
    tx.completed_at = _now()
    await db.flush()

    # Issue session
    ua, ip = _client_meta(request)
    session = await auth_service.issue_session(db, user, user_agent=ua, ip_address=ip)
    await db.commit()

    # Set cookies on response
    _apply_session(response, session)
    return MessageOut(message="2FA verified")


@router.post("/totp/setup", response_model=TotpSetupOut)
async def totp_setup(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TotpSetupOut:
    secret = totp_service.generate_totp_secret()
    current.totp_secret = secret
    current.totp_enabled = False
    await db.commit()
    uri = totp_service.provisioning_uri(secret=secret, email=current.email)
    return TotpSetupOut(secret=secret, provisioning_uri=uri)


@router.post("/totp/enable", response_model=MessageOut)
async def totp_enable(
    payload: TotpEnableRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    if not current.totp_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Run setup first")
    if not totp_service.verify_totp(secret=current.totp_secret, code=payload.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid code")
    current.totp_enabled = True
    await db.commit()
    return MessageOut(message="Two-factor authentication enabled")


@router.post("/totp/disable", response_model=MessageOut)
async def totp_disable(
    payload: TotpVerifyRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    if not current.totp_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="2FA is not enabled")

    # Verify the TOTP code before disabling
    if not totp_service.verify_totp(secret=current.totp_secret or "", code=payload.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid 2FA code")

    current.totp_enabled = False
    current.totp_secret = None
    await db.commit()
    return MessageOut(message="Two-factor authentication disabled")


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
    from app.config import settings
    from app.services import email_service

    link = f"{settings.frontend_url}/reset-password?token={token}"
    email_service.send_password_reset(to=email, reset_url=link)
