"""Public invite acceptance routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cookies import set_auth_cookies
from app.database import get_db
from app.schemas.practice import AcceptInviteRequest, InvitePreview
from app.schemas.auth import UserOut
from app.services import auth_service, invite_service, practice_service

router = APIRouter(prefix="/api/invites", tags=["invites"])


@router.get("/preview", response_model=InvitePreview)
async def preview_invite(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> InvitePreview:
    invite = await invite_service.get_valid_invite(db, token)
    if invite is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid or expired invite")

    practice = await practice_service.get_practice(db, invite.practice_id)
    return InvitePreview(
        email=invite.email,
        first_name=invite.first_name,
        last_name=invite.last_name,
        practice_name=practice.name if practice else "Practice",
        invite_type=invite.invite_type.value,
        expires_at=invite.expires_at.isoformat(),
    )


@router.post("/accept", response_model=UserOut)
async def accept_invite(
    request: Request,
    response: Response,
    payload: AcceptInviteRequest,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    invite = await invite_service.get_valid_invite(db, payload.token)
    if invite is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid or expired invite")

    practice = await practice_service.get_practice(db, invite.practice_id)
    if practice is None or not practice.is_active:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=auth_service.PRACTICE_INACTIVE_MESSAGE,
        )

    user = await invite_service.accept_invite(db, invite, password=payload.password)

    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    session = await auth_service.issue_session(db, user, user_agent=ua, ip_address=ip)
    await db.commit()

    set_auth_cookies(
        response,
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        csrf_token=session.csrf_token,
    )
    return UserOut.model_validate(user)
