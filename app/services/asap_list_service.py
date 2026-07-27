"""ASAP list: patients with future appointments marked ready for earlier openings."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_context import StaffContext
from app.models.staff import ActivityType, Appointment, AppointmentStatus, Patient
from app.schemas.staff import AsapListCreate
from app.services import appointment_rules_service, staff_service


async def list_asap(db: AsyncSession, ctx: StaffContext) -> list[tuple[Appointment, Patient]]:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Appointment, Patient)
        .join(Patient, Patient.id == Appointment.patient_id)
        .where(
            Appointment.practice_id == ctx.practice_id,
            Appointment.location_id == ctx.location_id,
            Appointment.starts_at > now,
            Appointment.status != AppointmentStatus.CANCELLED,
        )
        .order_by(Appointment.starts_at)
    )
    rows = [(a, p) for a, p in result.all() if (a.meta or {}).get("asap")]
    return rows


async def add_to_asap(db: AsyncSession, ctx: StaffContext, data: AsapListCreate) -> Appointment:
    patient = await staff_service.get_patient(db, ctx, data.patient_id)
    if patient is None:
        raise ValueError("Patient not found")

    if data.appointment_id is not None:
        result = await db.execute(
            select(Appointment).where(
                Appointment.id == data.appointment_id,
                Appointment.practice_id == ctx.practice_id,
                Appointment.location_id == ctx.location_id,
                Appointment.patient_id == data.patient_id,
            )
        )
        appt = result.scalar_one_or_none()
        if appt is None:
            raise ValueError("Appointment not found for this patient")
        if appt.status == AppointmentStatus.CANCELLED:
            raise ValueError("Cannot mark a cancelled appointment as ASAP")
        appt.meta = {**(appt.meta or {}), "asap": True, "asap_notes": data.notes.strip()}
        await db.flush()
        await staff_service._log_activity(  # noqa: SLF001
            db,
            patient_id=patient.id,
            activity_type=ActivityType.NOTE,
            title="Added to ASAP list",
            meta={"appointment_id": str(appt.id)},
        )
        return appt

    if data.starts_at is None:
        raise ValueError("Select an appointment date or pick an existing appointment")

    mapping_context = appointment_rules_service.MappingContext(provider_name=data.provider_name)
    appt_type, meta = await appointment_rules_service.resolve_appointment_type(
        db,
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        appointment_type_id=data.appointment_type_id,
        appointment_type_name=data.appointment_type or None,
        mapping_context=mapping_context,
        source="staff",
    )
    type_name = appt_type.name if appt_type else (data.appointment_type or "Appointment")
    duration = appt_type.duration_minutes if appt_type else data.duration_minutes

    appt = Appointment(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        patient_id=data.patient_id,
        provider_name=data.provider_name,
        appointment_type=type_name,
        appointment_type_def_id=appt_type.id if appt_type else None,
        starts_at=data.starts_at if data.starts_at.tzinfo else data.starts_at.replace(tzinfo=timezone.utc),
        duration_minutes=duration,
        status=AppointmentStatus.UNCONFIRMED,
        meta={**meta, "asap": True, "asap_notes": data.notes.strip()},
    )
    db.add(appt)
    await db.flush()
    await staff_service._log_activity(  # noqa: SLF001
        db,
        patient_id=patient.id,
        activity_type=ActivityType.APPOINTMENT,
        title=f"Added to ASAP list — {type_name}",
        meta={"appointment_id": str(appt.id), "asap": True},
    )
    return appt


async def remove_from_asap(db: AsyncSession, ctx: StaffContext, appointment_id: uuid.UUID) -> Appointment | None:
    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.practice_id == ctx.practice_id,
            Appointment.location_id == ctx.location_id,
        )
    )
    appt = result.scalar_one_or_none()
    if appt is None:
        return None
    meta = dict(appt.meta or {})
    meta.pop("asap", None)
    meta.pop("asap_notes", None)
    appt.meta = meta
    await db.flush()
    return appt
