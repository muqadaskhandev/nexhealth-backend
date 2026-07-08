"""Single sign-on (OAuth2 / OIDC) routes for Google, Azure, and Okta."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.cookies import set_auth_cookies
from app.database import get_db
from app.models.user import AuthProvider, User, UserRole
from app.services import auth_service, oauth, user_service
from app.services.oauth import OAuthError

router = APIRouter(prefix="/api/auth/sso", tags=["sso"])

# Short-lived cookie carrying the OAuth transaction across the provider redirect.
_TX_COOKIE = "oauth_tx"
_PROVIDER_AUTH_MAP = {
    "google": AuthProvider.GOOGLE,
    "azure": AuthProvider.AZURE,
    "okta": AuthProvider.OKTA,
}


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


def _q(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")
