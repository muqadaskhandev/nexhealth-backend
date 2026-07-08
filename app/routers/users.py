"""Admin user-management routes.

All routes here require an ADMIN role (via require_admin). Admins can invite
users, assign locations and roles, deactivate accounts, and trigger resets.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.dependencies import require_admin
from app.database import get_db
from app.models.user import User
from app.schemas.auth import MessageOut
from app.schemas.location import LocationOut
from app.schemas.user import UserCreate, UserDetail, UserUpdate
from app.services import auth_service, user_service

router = APIRouter(prefix="/api/users", tags=["users"])


def _to_detail(user: User) -> UserDetail:
    locations = [
        LocationOut.model_validate(m.location)
        for m in sorted(user.memberships, key=lambda m: m.location.name)
    ]
    return UserDetail(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        full_name=user.full_name,
        initials=user.initials,
        role=user.role,
        auth_provider=user.auth_provider,
        is_active=user.is_active,
        email_verified=user.email_verified,
        locations=locations,
    )


@router.get("", response_model=list[UserDetail])
async def list_users(
    _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[UserDetail]:
    users = await user_service.list_users(db)
    return [_to_detail(u) for u in users]


@router.post("", response_model=UserDetail, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserDetail:
    existing = await user_service.get_user_by_email(db, payload.email)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already in use")

    password_hash = (
        security.hash_password(payload.password) if payload.password else None
    )
    user = await user_service.create_user(
        db,
        email=payload.email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        role=payload.role,
        password_hash=password_hash,
        location_ids=payload.location_ids,
    )
    await db.commit()
    user = await user_service.get_user_with_locations(db, user.id)
    return _to_detail(user)


@router.patch("/{user_id}", response_model=UserDetail)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserDetail:
    user = await user_service.get_user_with_locations(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.first_name is not None:
        user.first_name = payload.first_name
    if payload.last_name is not None:
        user.last_name = payload.last_name
    if payload.role is not None:
        # Guard: an admin cannot demote themselves (avoids locking out admins).
        if user.id == admin.id and payload.role != user.role:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="You cannot change your own role"
            )
        user.role = payload.role
    if payload.is_active is not None:
        if user.id == admin.id and payload.is_active is False:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate yourself"
            )
        user.is_active = payload.is_active
        if not payload.is_active:
            # Deactivation kills all sessions immediately.
            await auth_service._revoke_user_sessions(db, user.id)
    if payload.location_ids is not None:
        await user_service.set_user_locations(db, user, payload.location_ids)

    await db.commit()
    user = await user_service.get_user_with_locations(db, user.id)
    return _to_detail(user)


@router.post("/{user_id}/send-reset", response_model=MessageOut)
async def send_reset(
    user_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    user = await user_service.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    raw = await auth_service.create_password_reset(db, user)
    await db.commit()
    from app.routers.auth import _deliver_reset_email

    _deliver_reset_email(user.email, raw)
    return MessageOut(message="Password reset link sent")
