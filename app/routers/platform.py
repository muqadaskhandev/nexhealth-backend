"""Platform super-admin routes: onboard practices."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_super_admin
from app.database import get_db
from app.models.invite import InviteType
from app.models.user import User
from app.schemas.location import LocationOut, LocationUpdate
from app.schemas.practice import (
    LocationCreate,
    PracticeCreate,
    PlatformPracticeUpdate,
    PracticeOut,
)
from app.services import auth_service, invite_service, practice_service, user_service

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
    """Create practice + one or more locations + invite Practice Admin via SES."""
    from app.services import user_service

    existing = await user_service.get_user_by_email(db, payload.admin_email)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Admin email already in use")

    products = (
        payload.enabled_products.model_dump()
        if payload.enabled_products
        else None
    )
    location_payloads = [
        loc.model_dump() for loc in payload.locations if loc.name.strip()
    ]
    practice, _locations = await practice_service.create_practice(
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
        locations=location_payloads or None,
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
    payload: PlatformPracticeUpdate,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> PracticeOut:
    """Update an onboarded practice (profile, plan, and active flag)."""
    practice = await practice_service.get_practice_with_locations(db, practice_id)
    if practice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Practice not found")

    products = (
        payload.enabled_products.model_dump()
        if payload.enabled_products is not None
        else None
    )
    data = payload.model_dump(exclude_unset=True)
    if "enabled_products" in data:
        data["enabled_products"] = products

    await practice_service.update_practice(db, practice, **data)

    # Deactivating a practice immediately kicks out all of its users.
    if data.get("is_active") is False:
        await auth_service.revoke_practice_sessions(db, practice.id)

    await db.commit()

    practice = await practice_service.get_practice_with_locations(db, practice_id)
    return _practice_out(practice)


@router.post(
    "/practices/{practice_id}/locations",
    response_model=LocationOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_practice_location(
    practice_id: uuid.UUID,
    payload: LocationCreate,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> LocationOut:
    """Add an office to an existing practice and grant practice admins access."""
    practice = await practice_service.get_practice(db, practice_id)
    if practice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Practice not found")

    location = await practice_service.create_location_for_practice(
        db,
        practice,
        name=payload.name,
        address=payload.address,
        address_line2=payload.address_line2,
        city=payload.city,
        state=payload.state,
        zip_code=payload.zip_code,
        phone=payload.phone,
        email=payload.email,
    )
    await user_service.grant_location_to_practice_admins(db, practice.id, location.id)
    await db.commit()
    await db.refresh(location)
    return LocationOut.model_validate(location)


@router.patch(
    "/practices/{practice_id}/locations/{location_id}",
    response_model=LocationOut,
)
async def update_practice_location(
    practice_id: uuid.UUID,
    location_id: uuid.UUID,
    payload: LocationUpdate,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> LocationOut:
    location = await practice_service.get_practice_location(db, practice_id, location_id)
    if location is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Location not found")

    await practice_service.update_location(
        db,
        location,
        **payload.model_dump(exclude_unset=True),
    )
    await db.commit()
    await db.refresh(location)
    return LocationOut.model_validate(location)


@router.delete(
    "/practices/{practice_id}/locations/{location_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_practice_location(
    practice_id: uuid.UUID,
    location_id: uuid.UUID,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    location = await practice_service.get_practice_location(db, practice_id, location_id)
    if location is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Location not found")

    practice = await practice_service.get_practice_with_locations(db, practice_id)
    if practice is not None and len(practice.locations) <= 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="A practice must keep at least one location.",
        )

    await practice_service.delete_location(db, location)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/practices/{practice_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_practice(
    practice_id: uuid.UUID,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    practice = await practice_service.get_practice(db, practice_id)
    if practice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Practice not found")

    await auth_service.revoke_practice_sessions(db, practice.id)
    await practice_service.delete_practice(db, practice)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
