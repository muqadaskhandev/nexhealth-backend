"""Platform super-admin routes: onboard practices."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_super_admin
from app.database import get_db
from app.models.invite import InviteType
from app.models.user import User
from app.schemas.location import LocationOut
from app.schemas.practice import PracticeCreate, PracticeOut, PracticeUpdate
from app.services import invite_service, practice_service

router = APIRouter(prefix="/api/platform", tags=["platform"])


def _practice_out(practice) -> PracticeOut:
    return PracticeOut(
        id=practice.id,
        name=practice.name,
        logo_url=practice.logo_url,
        address=practice.address,
        city=practice.city,
        state=practice.state,
        zip_code=practice.zip_code,
        phone=practice.phone,
        booking_redirect_url=practice.booking_redirect_url or "",
        subscription_plan=practice.subscription_plan,
        enabled_products=practice.enabled_products,
        ehr_system=practice.ehr_system,
        sync_status=practice.sync_status,
        sync_error=practice.sync_error,
        is_active=practice.is_active,
        locations=[LocationOut.model_validate(loc) for loc in practice.locations],
    )


@router.get("/practices", response_model=list[PracticeOut])
async def list_practices(
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> list[PracticeOut]:
    practices = await practice_service.list_practices(db)
    return [_practice_out(p) for p in practices]


@router.post("/practices", response_model=PracticeOut, status_code=status.HTTP_201_CREATED)
async def onboard_practice(
    payload: PracticeCreate,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> PracticeOut:
    """Create practice + default location + invite Practice Admin via SES."""
    from app.services import user_service

    existing = await user_service.get_user_by_email(db, payload.admin_email)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Admin email already in use")

    products = (
        payload.enabled_products.model_dump()
        if payload.enabled_products
        else None
    )
    practice, location = await practice_service.create_practice(
        db,
        name=payload.name,
        address=payload.address,
        city=payload.city,
        state=payload.state,
        zip_code=payload.zip_code,
        phone=payload.phone,
        subscription_plan=payload.subscription_plan,
        enabled_products=products,
        default_location_name=payload.default_location_name,
    )

    await invite_service.create_invite(
        db,
        practice_id=practice.id,
        practice_name=practice.name,
        email=payload.admin_email,
        first_name=payload.admin_first_name,
        last_name=payload.admin_last_name,
        invite_type=InviteType.PRACTICE_ADMIN,
    )
    await db.commit()

    practice = await practice_service.get_practice_with_locations(db, practice.id)
    return _practice_out(practice)


@router.get("/practices/{practice_id}", response_model=PracticeOut)
async def get_practice(
    practice_id: uuid.UUID,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> PracticeOut:
    practice = await practice_service.get_practice_with_locations(db, practice_id)
    if practice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Practice not found")
    return _practice_out(practice)


@router.patch("/practices/{practice_id}", response_model=PracticeOut)
async def update_practice(
    practice_id: uuid.UUID,
    payload: PracticeUpdate,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> PracticeOut:
    practice = await practice_service.get_practice_with_locations(db, practice_id)
    if practice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Practice not found")

    products = (
        payload.enabled_products.model_dump()
        if payload.enabled_products is not None
        else None
    )
    await practice_service.update_practice(
        db,
        practice,
        name=payload.name,
        logo_url=payload.logo_url,
        address=payload.address,
        city=payload.city,
        state=payload.state,
        zip_code=payload.zip_code,
        phone=payload.phone,
        enabled_products=products,
    )
    await db.commit()

    practice = await practice_service.get_practice_with_locations(db, practice_id)
    return _practice_out(practice)
