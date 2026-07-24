"""Business logic for waitlist requests: slots, candidate patients, sending, claiming."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_context import StaffContext
from app.models.staff import Appointment, AppointmentStatus, Message, MessageChannel, MessageThread, Patient
from app.models.waitlist import WaitlistRequest, WaitlistRequestPatient, WaitlistRequestSlot, WaitlistRequestStatus
from app.schemas.waitlist_requests import WaitlistRequestCreate
from app.services import providers_service

EXPIRY_BUFFER_MINUTES = 15


async def _get_or_create_thread(db: AsyncSession, ctx: StaffContext, patient_id: uuid.UUID) -> MessageThread:
    result = await db.execute(
        select(MessageThread).where(
            MessageThread.practice_id == ctx.practice_id,
            MessageThread.location_id == ctx.location_id,
            MessageThread.patient_id == patient_id,
        )
    )
    thread = result.scalars().first()
    if thread is None:
        thread = MessageThread(practice_id=ctx.practice_id, location_id=ctx.location_id, patient_id=patient_id)
        db.add(thread)
        await db.flush()
    return thread


def _slot_message_body(slots: list[WaitlistRequestSlot]) -> str:
    if len(slots) == 1:
        when = slots[0].starts_at.strftime("%A, %B %-d at %-I:%M %p")
        return f"We haven't seen you in a while. An earlier appointment time just opened up: {when}. Tap Book now to claim it."
    return f"We haven't seen you in a while. {len(slots)} earlier appointment times just opened up. Tap Book now to claim one."


async def create_and_send_request(
    db: AsyncSession, ctx: StaffContext, data: WaitlistRequestCreate
) -> WaitlistRequest:
    for slot in data.slots:
        if slot.ends_at <= slot.starts_at:
            raise ValueError("Each slot's end time must be after its start time")
        provider = await providers_service.get_provider(db, ctx, slot.provider_id)
        if provider is None:
            raise ValueError("Provider not found")
        if slot.operatory_id is not None:
            operatory = await providers_service.get_operatory(db, ctx, slot.operatory_id)
            if operatory is None:
                raise ValueError("Operatory not found")

    request = WaitlistRequest(practice_id=ctx.practice_id, location_id=ctx.location_id)
    db.add(request)
    await db.flush()

    slot_rows: list[WaitlistRequestSlot] = []
    for slot in data.slots:
        row = WaitlistRequestSlot(
            waitlist_request_id=request.id,
            provider_id=slot.provider_id,
            operatory_id=slot.operatory_id,
            starts_at=slot.starts_at,
            ends_at=slot.ends_at,
        )
        db.add(row)
        slot_rows.append(row)
    await db.flush()

    body = _slot_message_body(slot_rows)
    now = datetime.now(timezone.utc)
    for patient_id in data.patient_ids:
        patient = await db.get(Patient, patient_id)
        if patient is None or patient.practice_id != ctx.practice_id:
            raise ValueError(f"Patient {patient_id} not found")

        db.add(WaitlistRequestPatient(waitlist_request_id=request.id, patient_id=patient_id, notified_at=now))

        thread = await _get_or_create_thread(db, ctx, patient_id)
        db.add(Message(thread_id=thread.id, direction="outbound", body=body, channel=MessageChannel.SMS, sent_at=now))

    await db.flush()
    return request


async def list_requests(db: AsyncSession, ctx: StaffContext) -> list[WaitlistRequest]:
    result = await db.execute(
        select(WaitlistRequest)
        .where(WaitlistRequest.practice_id == ctx.practice_id, WaitlistRequest.location_id == ctx.location_id)
        .order_by(WaitlistRequest.created_at.desc())
    )
    return list(result.scalars().all())


async def get_request(db: AsyncSession, ctx: StaffContext, request_id: uuid.UUID) -> WaitlistRequest | None:
    request = await db.get(WaitlistRequest, request_id)
    if request is None or request.practice_id != ctx.practice_id or request.location_id != ctx.location_id:
        return None
    return request


async def get_slots(db: AsyncSession, request_id: uuid.UUID) -> list[WaitlistRequestSlot]:
    result = await db.execute(
        select(WaitlistRequestSlot).where(WaitlistRequestSlot.waitlist_request_id == request_id)
    )
    return list(result.scalars().all())


async def get_patients(db: AsyncSession, request_id: uuid.UUID) -> list[tuple[WaitlistRequestPatient, Patient]]:
    result = await db.execute(
        select(WaitlistRequestPatient, Patient)
        .join(Patient, Patient.id == WaitlistRequestPatient.patient_id)
        .where(WaitlistRequestPatient.waitlist_request_id == request_id)
    )
    return [(wp, p) for wp, p in result.all()]


async def cancel_request(db: AsyncSession, request: WaitlistRequest) -> WaitlistRequest:
    request.status = WaitlistRequestStatus.CANCELLED
    await db.flush()
    return request


async def get_slot(db: AsyncSession, request_id: uuid.UUID, slot_id: uuid.UUID) -> WaitlistRequestSlot | None:
    slot = await db.get(WaitlistRequestSlot, slot_id)
    if slot is None or slot.waitlist_request_id != request_id:
        return None
    return slot


async def cancel_slot(db: AsyncSession, request: WaitlistRequest, slot: WaitlistRequestSlot) -> WaitlistRequestSlot:
    if slot.claimed_by_patient_id is not None:
        raise ValueError("This slot has already been claimed and can't be cancelled")
    if slot.cancelled_at is not None:
        raise ValueError("This slot has already been cancelled")
    slot.cancelled_at = datetime.now(timezone.utc)
    await db.flush()
    return slot


async def claim_slot(
    db: AsyncSession, ctx: StaffContext, request: WaitlistRequest, slot: WaitlistRequestSlot, patient_id: uuid.UUID
) -> WaitlistRequestSlot:
    if request.status == WaitlistRequestStatus.CANCELLED:
        raise ValueError("This waitlist request has been cancelled")
    if slot.cancelled_at is not None:
        raise ValueError("This slot has been cancelled")
    if slot.claimed_by_patient_id is not None:
        raise ValueError("This slot has already been claimed")
    now = datetime.now(timezone.utc)
    if now > slot.starts_at - timedelta(minutes=EXPIRY_BUFFER_MINUTES):
        raise ValueError("This slot has expired")

    patient = await db.get(Patient, patient_id)
    if patient is None or patient.practice_id != ctx.practice_id:
        raise ValueError("Patient not found")
    provider = await providers_service.get_provider(db, ctx, slot.provider_id)
    if provider is None:
        raise ValueError("Provider not found")

    duration_minutes = max(5, int((slot.ends_at - slot.starts_at).total_seconds() // 60))
    appointment = Appointment(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        patient_id=patient_id,
        provider_name=provider.name,
        starts_at=slot.starts_at,
        duration_minutes=duration_minutes,
        status=AppointmentStatus.UNCONFIRMED,
    )
    db.add(appointment)
    await db.flush()

    slot.claimed_by_patient_id = patient_id
    slot.claimed_at = now
    slot.created_appointment_id = appointment.id
    await db.flush()
    return slot


async def search_missed_cancelled(
    db: AsyncSession,
    ctx: StaffContext,
    *,
    missed: bool,
    cancelled: bool,
    start_date: date | None,
    end_date: date | None,
    exclude_recent_days: int,
) -> list[tuple[Patient, Appointment]]:
    now = datetime.now(timezone.utc)
    statuses = []
    if missed:
        statuses.append(AppointmentStatus.UNCONFIRMED)
    if cancelled:
        statuses.append(AppointmentStatus.CANCELLED)
    if not statuses:
        return []

    conditions = [
        Appointment.practice_id == ctx.practice_id,
        Appointment.location_id == ctx.location_id,
        Appointment.status.in_(statuses),
    ]
    if AppointmentStatus.UNCONFIRMED in statuses and AppointmentStatus.CANCELLED not in statuses:
        conditions.append(Appointment.starts_at < now)
    if start_date is not None:
        conditions.append(Appointment.starts_at >= datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc))
    if end_date is not None:
        conditions.append(Appointment.starts_at <= datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc))

    result = await db.execute(
        select(Appointment, Patient)
        .join(Patient, Patient.id == Appointment.patient_id)
        .where(and_(*conditions))
        .order_by(Appointment.starts_at.desc())
    )
    rows = result.all()

    # Exclude patients with any existing non-cancelled future appointment.
    future_result = await db.execute(
        select(Appointment.patient_id).where(
            Appointment.practice_id == ctx.practice_id,
            Appointment.location_id == ctx.location_id,
            Appointment.starts_at > now,
            Appointment.status != AppointmentStatus.CANCELLED,
        )
    )
    has_future = {row[0] for row in future_result.all()}

    # Exclude patients notified by any waitlist request within the exclusion window.
    recent_ids: set[uuid.UUID] = set()
    if exclude_recent_days > 0:
        cutoff = now - timedelta(days=exclude_recent_days)
        recent_result = await db.execute(
            select(WaitlistRequestPatient.patient_id)
            .join(WaitlistRequest, WaitlistRequest.id == WaitlistRequestPatient.waitlist_request_id)
            .where(
                WaitlistRequest.practice_id == ctx.practice_id,
                WaitlistRequest.location_id == ctx.location_id,
                WaitlistRequestPatient.notified_at >= cutoff,
            )
        )
        recent_ids = {row[0] for row in recent_result.all()}

    seen: set[uuid.UUID] = set()
    out: list[tuple[Patient, Appointment]] = []
    for appt, patient in rows:
        if patient.id in has_future or patient.id in recent_ids or patient.id in seen:
            continue
        seen.add(patient.id)
        out.append((patient, appt))
    return out
