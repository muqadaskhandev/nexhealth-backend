"""Custom online booking form fields and insurance list."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_context import StaffContext, get_staff_context
from app.database import get_db
from app.schemas.booking_form import (
    BookingFormFieldCreate,
    BookingFormFieldOut,
    BookingFormFieldReorder,
    BookingFormFieldUpdate,
    BookingInsuranceBulkCreate,
    BookingInsuranceCopyToLocations,
    BookingInsuranceCreate,
    BookingInsuranceOut,
)
from app.services import booking_form_service

router = APIRouter(tags=["booking-form"])


# ── Form fields ──────────────────────────────────────────────────────────────
@router.get("/api/booking-form-fields", response_model=list[BookingFormFieldOut])
async def list_form_fields(ctx: StaffContext = Depends(get_staff_context), db: AsyncSession = Depends(get_db)):
    rows = await booking_form_service.list_form_fields(db, ctx)
    return [BookingFormFieldOut.model_validate(r) for r in rows]


@router.post("/api/booking-form-fields", response_model=BookingFormFieldOut, status_code=status.HTTP_201_CREATED)
async def create_form_field(
    payload: BookingFormFieldCreate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        field = await booking_form_service.create_form_field(db, ctx, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return BookingFormFieldOut.model_validate(field)


@router.patch("/api/booking-form-fields/{field_id}", response_model=BookingFormFieldOut)
async def update_form_field(
    field_id: uuid.UUID,
    payload: BookingFormFieldUpdate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    field = await booking_form_service.get_form_field(db, ctx, field_id)
    if field is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Form field not found")
    try:
        field = await booking_form_service.update_form_field(db, field, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return BookingFormFieldOut.model_validate(field)


@router.delete("/api/booking-form-fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_form_field(
    field_id: uuid.UUID,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    field = await booking_form_service.get_form_field(db, ctx, field_id)
    if field is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Form field not found")
    await booking_form_service.delete_form_field(db, field)
    await db.commit()


@router.post("/api/booking-form-fields/reorder", response_model=list[BookingFormFieldOut])
async def reorder_form_fields(
    payload: BookingFormFieldReorder,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        rows = await booking_form_service.reorder_form_fields(db, ctx, payload.ordered_ids)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return [BookingFormFieldOut.model_validate(r) for r in rows]


# ── Insurances ───────────────────────────────────────────────────────────────
@router.get("/api/booking-insurances", response_model=list[BookingInsuranceOut])
async def list_insurances(ctx: StaffContext = Depends(get_staff_context), db: AsyncSession = Depends(get_db)):
    rows = await booking_form_service.list_insurances(db, ctx)
    return [BookingInsuranceOut.model_validate(r) for r in rows]


@router.post("/api/booking-insurances", response_model=BookingInsuranceOut, status_code=status.HTTP_201_CREATED)
async def create_insurance(
    payload: BookingInsuranceCreate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    insurance = await booking_form_service.create_insurance(db, ctx, payload.name)
    await db.commit()
    return BookingInsuranceOut.model_validate(insurance)


@router.post("/api/booking-insurances/bulk", response_model=list[BookingInsuranceOut], status_code=status.HTTP_201_CREATED)
async def bulk_create_insurances(
    payload: BookingInsuranceBulkCreate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    rows = await booking_form_service.bulk_create_insurances(
        db, ctx, payload.names, copy_to_all_locations=payload.copy_to_all_locations
    )
    await db.commit()
    return [BookingInsuranceOut.model_validate(r) for r in rows]


@router.post("/api/booking-insurances/copy")
async def copy_insurances(
    payload: BookingInsuranceCopyToLocations,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        copied = await booking_form_service.copy_insurances_to_locations(db, ctx, payload.location_ids)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return {"copied": copied}


@router.post("/api/booking-insurances/restore-defaults", response_model=list[BookingInsuranceOut])
async def restore_default_insurances(
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    rows = await booking_form_service.restore_default_insurances(db, ctx)
    await db.commit()
    return [BookingInsuranceOut.model_validate(r) for r in rows]


@router.delete("/api/booking-insurances/{insurance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_insurance(
    insurance_id: uuid.UUID,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    insurance = await booking_form_service.get_insurance(db, ctx, insurance_id)
    if insurance is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Insurance not found")
    await booking_form_service.delete_insurance(db, insurance)
    await db.commit()
