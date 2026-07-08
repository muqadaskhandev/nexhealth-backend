"""Location routes: list the user's locations and switch the active one."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cookies import ACCESS_COOKIE, set_auth_cookies
from app.core.dependencies import get_current_user
from app.core.security import generate_opaque_token
from app.database import get_db
from app.models.user import User
from app.schemas.location import LocationOut, SwitchLocationRequest
from app.services import auth_service, user_service

router = APIRouter(prefix="/api/locations", tags=["locations"])


@router.get("", response_model=list[LocationOut])
async def my_locations(
    current: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[LocationOut]:
    locations = await user_service.list_user_locations(db, current.id)
    return [LocationOut.model_validate(l) for l in locations]


@router.post("/switch", response_model=LocationOut)
async def switch_location(
    payload: SwitchLocationRequest,
    request: Request,
    response: Response,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LocationOut:
    """Switch the active location. Server-enforced: you can only switch into a
    location you're a member of. Re-mints the access-token cookie with the new
    location claim (keeping the same refresh session)."""
    if not await user_service.user_can_access_location(
        db, current.id, payload.location_id
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="You do not have access to that location"
        )

    session_id = getattr(request.state, "session_id", None)
    if session_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    import uuid

    new_access = await auth_service.issue_access_for_location(
        db, current, session_id=uuid.UUID(str(session_id)), location_id=payload.location_id
    )

    # Only the access-token cookie needs re-issuing; refresh stays put. We reuse
    # the existing CSRF cookie value if present, else mint a new one.
    csrf = request.cookies.get("csrf_token") or generate_opaque_token()
    # Re-issue only the access cookie by setting it directly.
    from app.config import settings

    response.set_cookie(
        ACCESS_COOKIE,
        new_access,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.access_token_ttl_minutes * 60,
        path="/",
        domain=settings.cookie_domain or None,
    )
    if request.cookies.get("csrf_token") is None:
        response.set_cookie(
            "csrf_token",
            csrf,
            httponly=False,
            secure=settings.cookie_secure,
            samesite=settings.cookie_samesite,
            max_age=settings.access_token_ttl_minutes * 60,
            path="/",
            domain=settings.cookie_domain or None,
        )

    locations = await user_service.list_user_locations(db, current.id)
    active = next((l for l in locations if l.id == payload.location_id), None)
    return LocationOut.model_validate(active)
