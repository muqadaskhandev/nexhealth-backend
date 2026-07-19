"""Practice admin settings: branding, locations, EHR sync, products."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_admin, require_practice_user
from app.database import get_db
from app.models.user import User
from app.schemas.location import LocationOut, LocationUpdate, LogoCopyRequest
from app.schemas.ehr_sync import (
    ConnectionTestOut,
    EhrConnectionOut,
    EhrCredentialsRequest,
    LocationEhrMappingRequest,
    SyncRunOut,
)
from app.schemas.practice import (
    EhrConnectRequest,
    LocationCreate,
    PracticeOut,
    PracticeUpdate,
    StaffInviteRequest,
)
from app.models.invite import InviteType
from app.services import invite_service, logo_storage, practice_service, synchronizer_service, user_service

router = APIRouter(prefix="/api/practice", tags=["practice"])


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


async def _get_admin_practice(admin: User, db: AsyncSession):
    if admin.practice_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No practice linked")
    practice = await practice_service.get_practice_with_locations(db, admin.practice_id)
    if practice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Practice not found")
    return practice


async def _get_admin_location(admin: User, db: AsyncSession, location_id: uuid.UUID):
    practice = await _get_admin_practice(admin, db)
    location = await practice_service.get_practice_location(db, practice.id, location_id)
    if location is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Location not found")
    return practice, location


@router.get("/me", response_model=PracticeOut)
async def my_practice(
    current: User = Depends(require_practice_user),
    db: AsyncSession = Depends(get_db),
) -> PracticeOut:
    practice = await _get_admin_practice(current, db)
    return _practice_out(practice)


@router.patch("/me", response_model=PracticeOut)
async def update_my_practice(
    payload: PracticeUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PracticeOut:
    practice = await _get_admin_practice(admin, db)
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
    practice = await practice_service.get_practice_with_locations(db, practice.id)
    return _practice_out(practice)


@router.post("/me/ehr", response_model=PracticeOut)
async def connect_ehr(
    payload: EhrConnectRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PracticeOut:
    """Select the practice EHR system and reset connector setup."""
    practice = await _get_admin_practice(admin, db)
    await practice_service.connect_ehr(db, practice, ehr_system=payload.ehr_system)
    await db.commit()
    practice = await practice_service.get_practice_with_locations(db, practice.id)
    return _practice_out(practice)


@router.get("/me/ehr/connection", response_model=EhrConnectionOut)
async def ehr_connection_status(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EhrConnectionOut:
    practice = await _get_admin_practice(admin, db)
    conn = await synchronizer_service.get_connection(db, practice.id)
    data = synchronizer_service.connection_out(practice, conn, practice.locations)
    return EhrConnectionOut(**data)


@router.post("/me/ehr/credentials", response_model=EhrConnectionOut)
async def save_ehr_credentials(
    payload: EhrCredentialsRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EhrConnectionOut:
    practice = await _get_admin_practice(admin, db)
    try:
        conn = await synchronizer_service.save_credentials(
            db,
            practice,
            connection_mode=payload.connection_mode,
            credentials=payload.credentials,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    practice = await practice_service.get_practice_with_locations(db, practice.id)
    data = synchronizer_service.connection_out(practice, conn, practice.locations)
    return EhrConnectionOut(**data)


@router.put("/me/ehr/locations", response_model=PracticeOut)
async def map_ehr_locations(
    payload: LocationEhrMappingRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PracticeOut:
    practice = await _get_admin_practice(admin, db)
    try:
        await synchronizer_service.map_locations(
            db,
            practice,
            [m.model_dump() for m in payload.mappings],
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    practice = await practice_service.get_practice_with_locations(db, practice.id)
    return _practice_out(practice)


@router.post("/me/ehr/test", response_model=ConnectionTestOut)
async def test_ehr_connection(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ConnectionTestOut:
    practice = await _get_admin_practice(admin, db)
    result = await synchronizer_service.test_connection(db, practice, practice.locations)
    await db.commit()
    practice = await practice_service.get_practice_with_locations(db, practice.id)
    return ConnectionTestOut(
        ok=result.ok,
        message=result.message,
        sync_status=practice.sync_status,
    )


@router.post("/me/ehr/sync", response_model=SyncRunOut)
async def run_ehr_sync(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SyncRunOut:
    practice = await _get_admin_practice(admin, db)
    try:
        imported, updated, message = await synchronizer_service.run_initial_sync(
            db, practice, practice.locations
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    practice = await practice_service.get_practice_with_locations(db, practice.id)
    return SyncRunOut(
        ok=True,
        message=message,
        patients_imported=imported,
        patients_updated=updated,
        sync_status=practice.sync_status,
    )


@router.post("/locations", response_model=LocationOut, status_code=status.HTTP_201_CREATED)
async def add_location(
    payload: LocationCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LocationOut:
    practice = await _get_admin_practice(admin, db)
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
    # Grant the creating admin access so it appears in their location switcher.
    current = await user_service.list_user_locations(db, admin.id)
    await user_service.set_user_locations(
        db, admin, [*(loc.id for loc in current), location.id]
    )
    await db.commit()
    await db.refresh(location)
    return LocationOut.model_validate(location)


@router.patch("/locations/{location_id}", response_model=LocationOut)
async def update_location(
    location_id: uuid.UUID,
    payload: LocationUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LocationOut:
    _, location = await _get_admin_location(admin, db, location_id)
    await practice_service.update_location(
        db,
        location,
        **payload.model_dump(exclude_unset=True),
    )
    await db.commit()
    await db.refresh(location)
    return LocationOut.model_validate(location)


@router.post("/locations/{location_id}/logo", response_model=LocationOut)
async def upload_location_logo(
    location_id: uuid.UUID,
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LocationOut:
    practice, location = await _get_admin_location(admin, db, location_id)
    try:
        url = await logo_storage.save_logo_upload(location.id, file)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    old = location.logo_url
    location.logo_url = url
    # Keep practice logo in sync when updating the first/default branding.
    if practice.logo_url in (None, "", old):
        practice.logo_url = url
    await db.commit()
    await db.refresh(location)
    return LocationOut.model_validate(location)


@router.delete("/locations/{location_id}/logo", response_model=LocationOut)
async def remove_location_logo(
    location_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LocationOut:
    practice, location = await _get_admin_location(admin, db, location_id)
    old = location.logo_url
    location.logo_url = None
    if practice.logo_url == old:
        practice.logo_url = None
    await db.commit()
    await db.refresh(location)
    return LocationOut.model_validate(location)


@router.post("/locations/{location_id}/logo/copy", response_model=list[LocationOut])
async def copy_location_logo(
    location_id: uuid.UUID,
    payload: LogoCopyRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[LocationOut]:
    practice, source = await _get_admin_location(admin, db, location_id)
    if not source.logo_url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Source location has no logo")

    updated: list = []
    for target_id in payload.location_ids:
        if target_id == source.id:
            continue
        target = await practice_service.get_practice_location(db, practice.id, target_id)
        if target is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=f"Location {target_id} not found",
            )
        target.logo_url = source.logo_url
        updated.append(target)

    await db.commit()
    for loc in updated:
        await db.refresh(loc)
    return [LocationOut.model_validate(loc) for loc in updated]


@router.post("/invite-staff", status_code=status.HTTP_201_CREATED)
async def invite_staff(
    payload: StaffInviteRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    practice = await _get_admin_practice(admin, db)
    existing = await user_service.get_user_by_email(db, payload.email)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already in use")

    practice_loc_ids = {loc.id for loc in practice.locations}
    if not set(payload.location_ids).issubset(practice_loc_ids):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="One or more locations do not belong to this practice",
        )

    await invite_service.create_invite(
        db,
        practice_id=practice.id,
        practice_name=practice.name,
        email=payload.email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        invite_type=InviteType.STAFF,
        inviter_name=admin.full_name,
        role=payload.role,
        location_ids=payload.location_ids,
    )
    await db.commit()
    return {"message": f"Invitation sent to {payload.email}"}
