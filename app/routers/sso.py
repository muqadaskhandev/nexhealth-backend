"""Single sign-on (OAuth2 / OIDC) routes for Google, Azure, and Okta."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core import security
from app.core.cookies import set_auth_cookies
from app.database import get_db
from app.models.token import SsoTotpTransaction
from app.models.user import AuthProvider, User, UserRole
from app.schemas.auth import MessageOut, TotpVerifyRequest
from app.services import auth_service, oauth, totp_service, user_service
from app.services.oauth import OAuthError

router = APIRouter(prefix="/api/auth/sso", tags=["sso"])

# Short-lived cookie carrying the OAuth transaction across the provider redirect.
_TX_COOKIE = "oauth_tx"
_PROVIDER_AUTH_MAP = {
    "google": AuthProvider.GOOGLE,
    "azure": AuthProvider.AZURE,
    "okta": AuthProvider.OKTA,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _frontend_redirect(path: str) -> RedirectResponse:
    return RedirectResponse(url=f"{settings.frontend_url.rstrip('/')}{path}", status_code=302)


@router.get("/{provider}/login")
async def sso_login(provider: str) -> RedirectResponse:
    """Kick off the OAuth flow by redirecting the browser to the provider."""
    try:
        start = await oauth.begin_login(provider)
    except OAuthError as exc:
        return _frontend_redirect(f"/login?sso_error={_q(exc.message)}")

    response = RedirectResponse(url=start.authorize_url, status_code=302)
    # httpOnly + short max-age; scoped to the SSO path only.
    response.set_cookie(
        _TX_COOKIE,
        start.tx_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",  # must be lax so it survives the provider redirect back
        max_age=600,
        path="/api/auth/sso",
        domain=settings.cookie_domain or None,
    )
    return response


@router.get("/{provider}/callback")
async def sso_callback(
    provider: str,
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Handle the provider redirect, provision/lookup the user, start a session."""
    if error:
        return _frontend_redirect(f"/login?sso_error={_q(error)}")

    tx_token = request.cookies.get(_TX_COOKIE)
    if not tx_token or not code or not state:
        return _frontend_redirect("/login?sso_error=invalid_sso_response")

    try:
        identity = await oauth.complete_login(
            tx_token=tx_token, returned_state=state, code=code
        )
    except OAuthError as exc:
        return _frontend_redirect(f"/login?sso_error={_q(exc.message)}")

    user = await user_service.get_user_by_email(db, identity.email)

    if user is None:
        # Provision a new SSO user. New SSO users get MEMBER role and no
        # locations until an admin assigns them — they can log in but see an
        # empty location list. (Tighten to "deny unknown" here if you require
        # pre-provisioning.)
        user = await user_service.create_user(
            db,
            email=identity.email,
            first_name=identity.first_name,
            last_name=identity.last_name,
            role=UserRole.MEMBER,
            auth_provider=_PROVIDER_AUTH_MAP.get(provider, AuthProvider.PASSWORD),
            email_verified=identity.email_verified,
        )
    elif not user.is_active:
        return _frontend_redirect("/login?sso_error=account_disabled")

    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None

    # If user has TOTP enabled, redirect to 2FA verification instead of creating session
    if user.totp_enabled:
        # Create a temporary transaction token for the 2FA flow
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

        response = _frontend_redirect(f"/sso-2fa?tx={_q(raw_tx)}")
        response.delete_cookie(_TX_COOKIE, path="/api/auth/sso", domain=settings.cookie_domain or None)
        return response

    session = await auth_service.issue_session(db, user, user_agent=ua, ip_address=ip)
    await db.commit()

    response = _frontend_redirect("/")
    set_auth_cookies(
        response,
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        csrf_token=session.csrf_token,
    )
    response.delete_cookie(_TX_COOKIE, path="/api/auth/sso", domain=settings.cookie_domain or None)
    return response


@router.post("/totp/verify", response_model=MessageOut)
async def sso_totp_verify(
    payload: TotpVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    """Verify TOTP code during SSO 2FA flow and create session."""
    from sqlalchemy import select

    # Get the transaction token from headers or body
    tx_token = request.headers.get("X-SSO-TOTP-TX") or request.query_params.get("tx")
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

    if not totp_service.verify_totp(secret=user.totp_secret or "", code=payload.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid 2FA code")

    # Mark transaction as completed
    tx.completed_at = _now()
    await db.flush()

    # Issue session
    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    session = await auth_service.issue_session(db, user, user_agent=ua, ip_address=ip)
    await db.commit()

    # Set cookies on response
    set_auth_cookies(
        response,
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        csrf_token=session.csrf_token,
    )
    return MessageOut(message="2FA verified")


def _q(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")
