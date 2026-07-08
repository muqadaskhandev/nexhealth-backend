"""Auth cookie management.

Three cookies make up a session:
  - access_token  : short-lived JWT (httpOnly) — sent on every request
  - refresh_token : opaque rotating token (httpOnly, path-scoped to /refresh)
  - csrf_token    : readable by JS (NOT httpOnly) for the double-submit pattern

httpOnly keeps the auth tokens unreadable by JavaScript, which neutralises
token exfiltration via XSS. The CSRF cookie is intentionally readable so the
SPA can echo it back in the X-CSRF-Token header.
"""
from __future__ import annotations

from fastapi import Response

from app.config import settings

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"

# Refresh cookie is scoped so it is only ever sent to the refresh/logout routes.
REFRESH_PATH = "/api/auth"


def _common(max_age: int) -> dict:
    kw: dict = {
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "max_age": max_age,
    }
    if settings.cookie_domain:
        kw["domain"] = settings.cookie_domain
    return kw


def set_auth_cookies(
    response: Response, *, access_token: str, refresh_token: str, csrf_token: str
) -> None:
    access_max = settings.access_token_ttl_minutes * 60
    refresh_max = settings.refresh_token_ttl_days * 24 * 3600

    response.set_cookie(
        ACCESS_COOKIE, access_token, httponly=True, path="/", **_common(access_max)
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        httponly=True,
        path=REFRESH_PATH,
        **_common(refresh_max),
    )
    # Not httpOnly: the frontend must read this to set the X-CSRF-Token header.
    response.set_cookie(
        CSRF_COOKIE, csrf_token, httponly=False, path="/", **_common(refresh_max)
    )


def clear_auth_cookies(response: Response) -> None:
    domain = settings.cookie_domain or None
    response.delete_cookie(ACCESS_COOKIE, path="/", domain=domain)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, domain=domain)
    response.delete_cookie(CSRF_COOKIE, path="/", domain=domain)
