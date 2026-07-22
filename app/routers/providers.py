"""Providers, operatories, and provider availability slots for online booking."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_context import StaffContext, get_staff_context
from app.database import get_db
from app.schemas.providers import (
    AvailabilitySlotCreate,
    AvailabilitySlotOut,
    AvailabilitySlotUpdate,
    OperatoryCreate,
    OperatoryOut,
    OperatoryUpdate,
    ProviderCreate,
    ProviderOut,
    ProviderUpdate,
)
from app.services import providers_service

router = APIRouter(tags=["providers"])


# ── Providers ────────────────────────────────────────────────────────────────
@router.get("/api/providers", response_model=list[ProviderOut])
async def list_providers(ctx: StaffContext = Depends(get_staff_context), db: AsyncSession = Depends(get_db)):
    rows = await providers_service.list_providers(db, ctx)
    return [ProviderOut.model_validate(r) for r in rows]


@router.post("/api/providers", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(
    payload: ProviderCreate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    provider = await providers_service.create_provider(db, ctx, payload)
    await db.commit()
    return ProviderOut.model_validate(provider)


@router.patch("/api/providers/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: uuid.UUID,
    payload: ProviderUpdate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    provider = await providers_service.get_provider(db, ctx, provider_id)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Provider not found")
    provider = await providers_service.update_provider(db, provider, payload)
    await db.commit()
    return ProviderOut.model_validate(provider)


@router.delete("/api/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: uuid.UUID,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    provider = await providers_service.get_provider(db, ctx, provider_id)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Provider not found")
    await providers_service.delete_provider(db, provider)
    await db.commit()


# ── Operatories ──────────────────────────────────────────────────────────────
@router.get("/api/operatories", response_model=list[OperatoryOut])
async def list_operatories(ctx: StaffContext = Depends(get_staff_context), db: AsyncSession = Depends(get_db)):
    rows = await providers_service.list_operatories(db, ctx)
    return [OperatoryOut.model_validate(r) for r in rows]


@router.post("/api/operatories", response_model=OperatoryOut, status_code=status.HTTP_201_CREATED)
async def create_operatory(
    payload: OperatoryCreate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    operatory = await providers_service.create_operatory(db, ctx, payload)
    await db.commit()
    return OperatoryOut.model_validate(operatory)


@router.patch("/api/operatories/{operatory_id}", response_model=OperatoryOut)
async def update_operatory(
    operatory_id: uuid.UUID,
    payload: OperatoryUpdate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    operatory = await providers_service.get_operatory(db, ctx, operatory_id)
    if operatory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Operatory not found")
    operatory = await providers_service.update_operatory(db, operatory, payload)
    await db.commit()
    return OperatoryOut.model_validate(operatory)


@router.delete("/api/operatories/{operatory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_operatory(
    operatory_id: uuid.UUID,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    operatory = await providers_service.get_operatory(db, ctx, operatory_id)
    if operatory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Operatory not found")
    await providers_service.delete_operatory(db, operatory)
    await db.commit()


# ── Availability slots ───────────────────────────────────────────────────────
@router.get("/api/availability-slots", response_model=list[AvailabilitySlotOut])
async def list_availability_slots(
    provider_id: uuid.UUID | None = Query(default=None),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    rows = await providers_service.list_availability_slots(db, ctx, provider_id)
    return [AvailabilitySlotOut.model_validate(r) for r in rows]


@router.post("/api/availability-slots", response_model=AvailabilitySlotOut, status_code=status.HTTP_201_CREATED)
async def create_availability_slot(
    payload: AvailabilitySlotCreate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        slot = await providers_service.create_availability_slot(db, ctx, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return AvailabilitySlotOut.model_validate(slot)


@router.patch("/api/availability-slots/{slot_id}", response_model=AvailabilitySlotOut)
async def update_availability_slot(
    slot_id: uuid.UUID,
    payload: AvailabilitySlotUpdate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    slot = await providers_service.get_availability_slot(db, ctx, slot_id)
    if slot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Availability slot not found")
    try:
        slot = await providers_service.update_availability_slot(db, ctx, slot, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return AvailabilitySlotOut.model_validate(slot)


@router.delete("/api/availability-slots/{slot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_availability_slot(
    slot_id: uuid.UUID,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    slot = await providers_service.get_availability_slot(db, ctx, slot_id)
    if slot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Availability slot not found")
    await providers_service.delete_availability_slot(db, slot)
    await db.commit()


@router.post("/api/availability-slots/{slot_id}/clone", response_model=AvailabilitySlotOut, status_code=status.HTTP_201_CREATED)
async def clone_availability_slot(
    slot_id: uuid.UUID,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    slot = await providers_service.get_availability_slot(db, ctx, slot_id)
    if slot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Availability slot not found")
    clone = await providers_service.clone_availability_slot(db, ctx, slot)
    await db.commit()
    return AvailabilitySlotOut.model_validate(clone)
