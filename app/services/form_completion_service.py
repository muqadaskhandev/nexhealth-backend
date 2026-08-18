"""Update scheduling when patient form intake completes."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.staff import Appointment, AppointmentStatus, FormRequest, FormRequestStatus, FormsStatus

ACTIVE_APPT = (AppointmentStatus.UNCONFIRMED, AppointmentStatus.CONFIRMED, AppointmentStatus.CHECKED_IN)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def appointment_out(appt: Appointment | None) -> dict | None:
    if appt is None:
        return None
    meta = appt.meta or {}
    return {
        "id": str(appt.id),
        "starts_at": appt.starts_at.isoformat(),
        "provider_name": appt.provider_name,
        "appointment_type": appt.appointment_type,
        "forms_status": appt.forms_status.value,
        "visit_reason": meta.get("visit_reason") or None,
        "visit_notes": meta.get("visit_notes") or None,
    }


async def get_upcoming_appointment(
    db: AsyncSession,
    *,
    patient_id: uuid.UUID,
    location_id: uuid.UUID,
) -> Appointment | None:
    now = _now()
    result = await db.execute(
        select(Appointment)
        .where(
            Appointment.patient_id == patient_id,
            Appointment.location_id == location_id,
            Appointment.status.in_(ACTIVE_APPT),
            Appointment.starts_at >= now,
        )
        .order_by(Appointment.starts_at.asc())
        .limit(1)
    )
    appt = result.scalar_one_or_none()
    if appt is not None:
        return appt

    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(Appointment)
        .where(
            Appointment.patient_id == patient_id,
            Appointment.location_id == location_id,
            Appointment.status.in_(ACTIVE_APPT),
            Appointment.starts_at >= start_of_day,
        )
        .order_by(Appointment.starts_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def resolve_visit(
    db: AsyncSession,
    *,
    patient_id: uuid.UUID,
    location_id: uuid.UUID,
    form_request_id: uuid.UUID | None = None,
    form_access_token_id: uuid.UUID | None = None,
) -> Appointment | None:
    if form_request_id is not None:
        req = await db.get(FormRequest, form_request_id)
        if req is not None and req.appointment_id is not None:
            appt = await db.get(Appointment, req.appointment_id)
            if appt is not None:
                return appt

    if form_access_token_id is not None:
        result = await db.execute(
            select(FormRequest)
            .where(
                FormRequest.form_access_token_id == form_access_token_id,
                FormRequest.patient_id == patient_id,
                FormRequest.archived_at.is_(None),
                FormRequest.appointment_id.is_not(None),
            )
            .order_by(FormRequest.sent_at.desc())
        )
        for req in result.scalars().all():
            if req.appointment_id is None:
                continue
            appt = await db.get(Appointment, req.appointment_id)
            if appt is not None:
                return appt

    return await get_upcoming_appointment(db, patient_id=patient_id, location_id=location_id)


async def sync_patient_forms_status(
    db: AsyncSession,
    *,
    patient_id: uuid.UUID,
    location_id: uuid.UUID,
    remaining_pending_forms: int,
    appointment_id: uuid.UUID | None = None,
) -> None:
    """Mark visit forms complete when outstanding requests for the visit (or all) are done."""
    now = _now()

    if appointment_id is not None:
        pending_for_visit = await db.execute(
            select(func.count())
            .select_from(FormRequest)
            .where(
                FormRequest.appointment_id == appointment_id,
                FormRequest.archived_at.is_(None),
                FormRequest.status != FormRequestStatus.COMPLETED,
            )
        )
        if int(pending_for_visit.scalar_one() or 0) == 0:
            appt = await db.get(Appointment, appointment_id)
            if appt is not None:
                if appt.forms_status == FormsStatus.INCOMPLETE:
                    appt.forms_status = FormsStatus.COMPLETE
                if appt.status == AppointmentStatus.UNCONFIRMED:
                    appt.status = AppointmentStatus.CONFIRMED
                    appt.meta = {**(appt.meta or {}), "confirmed_via": "intake"}
                    flag_modified(appt, "meta")

    if remaining_pending_forms > 0:
        await db.flush()
        return

    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(Appointment).where(
            Appointment.patient_id == patient_id,
            Appointment.location_id == location_id,
            Appointment.status.in_(ACTIVE_APPT),
            Appointment.starts_at >= start_of_day,
            Appointment.forms_status == FormsStatus.INCOMPLETE,
        )
    )
    for appt in result.scalars().all():
        appt.forms_status = FormsStatus.COMPLETE
        if appt.status == AppointmentStatus.UNCONFIRMED:
            appt.status = AppointmentStatus.CONFIRMED
            appt.meta = {**(appt.meta or {}), "confirmed_via": "intake"}
            flag_modified(appt, "meta")
    await db.flush()
