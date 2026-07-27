"""Appointment types, insertion rules, and mapping rules for online booking."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_context import StaffContext, get_staff_context
from app.database import get_db
from app.schemas.appointment_types import (
    AppointmentTypeCreate,
    AppointmentTypeOut,
    AppointmentTypeReorder,
    AppointmentTypeUpdate,
    BulkPatientTypeUpdate,
    BulkPatientTypeUpdateOut,
    CopyAppointmentTypesOut,
    CopyAppointmentTypesRequest,
    CopyMappingRulesOut,
    CopyMappingRulesRequest,
    MappingRetagOut,
    MappingRuleCreate,
    MappingRuleOut,
    MappingRuleReorder,
    MappingRuleUpdate,
)
from app.services import appointment_rules_service, appointment_types_service

router = APIRouter(tags=["appointment-types"])


# ── Appointment types ────────────────────────────────────────────────────────
@router.get("/api/appointment-types", response_model=list[AppointmentTypeOut])
async def list_appointment_types(
    location_id: uuid.UUID | None = Query(default=None),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        if location_id is not None:
            rows = await appointment_types_service.list_appointment_types_at_location(db, ctx, location_id)
        else:
            rows = await appointment_types_service.list_appointment_types(db, ctx)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return [AppointmentTypeOut.model_validate(r) for r in rows]


@router.post("/api/appointment-types", response_model=AppointmentTypeOut, status_code=status.HTTP_201_CREATED)
async def create_appointment_type(
    payload: AppointmentTypeCreate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    at = await appointment_types_service.create_appointment_type(db, ctx, payload)
    await db.commit()
    return AppointmentTypeOut.model_validate(at)


@router.patch("/api/appointment-types/{appointment_type_id}", response_model=AppointmentTypeOut)
async def update_appointment_type(
    appointment_type_id: uuid.UUID,
    payload: AppointmentTypeUpdate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    at = await appointment_types_service.get_appointment_type(db, ctx, appointment_type_id)
    if at is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Appointment type not found")
    at = await appointment_types_service.update_appointment_type(db, at, payload)
    await db.commit()
    return AppointmentTypeOut.model_validate(at)


@router.post("/api/appointment-types/reorder", response_model=list[AppointmentTypeOut])
async def reorder_appointment_types(
    payload: AppointmentTypeReorder,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        rows = await appointment_types_service.reorder_appointment_types(db, ctx, payload.ordered_ids)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return [AppointmentTypeOut.model_validate(r) for r in rows]


@router.post("/api/appointment-types/copy", response_model=CopyAppointmentTypesOut)
async def copy_appointment_types(
    payload: CopyAppointmentTypesRequest,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        copied = await appointment_types_service.copy_appointment_types(
            db, ctx, payload.appointment_type_ids, payload.location_ids
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return CopyAppointmentTypesOut(copied=copied)


@router.post("/api/appointment-types/bulk-patient-type", response_model=BulkPatientTypeUpdateOut)
async def bulk_update_patient_types(
    payload: BulkPatientTypeUpdate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        updated = await appointment_types_service.bulk_update_patient_types(
            db, ctx, payload.location_id, payload.updates
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return BulkPatientTypeUpdateOut(updated=updated)


@router.delete("/api/appointment-types/{appointment_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_appointment_type(
    appointment_type_id: uuid.UUID,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    at = await appointment_types_service.get_appointment_type(db, ctx, appointment_type_id)
    if at is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Appointment type not found")
    await appointment_types_service.delete_appointment_type(db, at)
    await db.commit()


# ── Mapping rules ────────────────────────────────────────────────────────────
@router.get("/api/mapping-rules", response_model=list[MappingRuleOut])
async def list_mapping_rules(
    ctx: StaffContext = Depends(get_staff_context), db: AsyncSession = Depends(get_db)
):
    rows = await appointment_types_service.list_mapping_rules(db, ctx)
    return [MappingRuleOut.model_validate(r) for r in rows]


@router.post("/api/mapping-rules", response_model=MappingRuleOut, status_code=status.HTTP_201_CREATED)
async def create_mapping_rule(
    payload: MappingRuleCreate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        rule = await appointment_types_service.create_mapping_rule(db, ctx, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await appointment_rules_service.retag_appointments_at_location(
        db, practice_id=ctx.practice_id, location_id=ctx.location_id
    )
    await db.commit()
    return MappingRuleOut.model_validate(rule)


@router.patch("/api/mapping-rules/{rule_id}", response_model=MappingRuleOut)
async def update_mapping_rule(
    rule_id: uuid.UUID,
    payload: MappingRuleUpdate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    rule = await appointment_types_service.get_mapping_rule(db, ctx, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Mapping rule not found")
    try:
        rule = await appointment_types_service.update_mapping_rule(db, ctx, rule, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await appointment_rules_service.retag_appointments_at_location(
        db, practice_id=ctx.practice_id, location_id=ctx.location_id
    )
    await db.commit()
    return MappingRuleOut.model_validate(rule)


@router.delete("/api/mapping-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mapping_rule(
    rule_id: uuid.UUID,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    rule = await appointment_types_service.get_mapping_rule(db, ctx, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Mapping rule not found")
    await appointment_types_service.delete_mapping_rule(db, rule)
    await db.commit()


@router.post("/api/mapping-rules/retag", response_model=MappingRetagOut)
async def retag_appointments(
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    updated = await appointment_rules_service.retag_appointments_at_location(
        db, practice_id=ctx.practice_id, location_id=ctx.location_id
    )
    await db.commit()
    return MappingRetagOut(updated=updated)


@router.post("/api/mapping-rules/copy", response_model=CopyMappingRulesOut)
async def copy_mapping_rules(
    payload: CopyMappingRulesRequest,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        copied = await appointment_types_service.copy_mapping_rules(
            db, ctx, payload.rule_ids, payload.location_ids
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return CopyMappingRulesOut(copied=copied)


@router.post("/api/mapping-rules/reorder", response_model=list[MappingRuleOut])
async def reorder_mapping_rules(
    payload: MappingRuleReorder,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        rows = await appointment_types_service.reorder_mapping_rules(db, ctx, payload.ordered_ids)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await appointment_rules_service.retag_appointments_at_location(
        db, practice_id=ctx.practice_id, location_id=ctx.location_id
    )
    await db.commit()
    return [MappingRuleOut.model_validate(r) for r in rows]
