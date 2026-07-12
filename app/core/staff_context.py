"""Practice staff context: active location + practice scoping."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_practice_user
from app.database import get_db
from app.models.user import User
from app.services import user_service


@dataclass(frozen=True)
class StaffContext:
    user: User
    practice_id: uuid.UUID
    location_id: uuid.UUID


async def get_staff_context(
    request: Request,
    user: User = Depends(require_practice_user),
    db: AsyncSession = Depends(get_db),
) -> StaffContext:
    if user.practice_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No practice linked to user")

    loc_raw = getattr(request.state, "active_location_id", None)
    if not loc_raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No active location selected")

    try:
        location_id = uuid.UUID(str(loc_raw))
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid active location")

    if not await user_service.user_can_access_location(db, user.id, location_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="No access to active location")

    return StaffContext(user=user, practice_id=user.practice_id, location_id=location_id)
