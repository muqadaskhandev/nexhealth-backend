"""Business logic for waitlist requests: slots, candidate patients, sending, claiming."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.staff_context import StaffContext
from app.models.location import Location
from app.models.practice import Practice
from app.models.providers import Provider
from app.models.staff import ActivityType, Appointment, AppointmentStatus, Message, MessageChannel, MessageThread, Patient
from app.models.waitlist import (
    WaitlistRequest,
    WaitlistRequestPatient,
    WaitlistRequestSlot,
    WaitlistRequestStatus,
    WaitlistTemplateType,
)
from app.schemas.waitlist_requests import WaitlistRequestCreate
from app.services import appointment_rules_service, providers_service, staff_service
from app.services.booking_availability_service import practice_slug

EXPIRY_BUFFER_MINUTES = 15
SMART_SEND_THRESHOLD = 100
SMART_SEND_BATCH_SIZE = 10
SMART_SEND_INTERVAL_MINUTES = 5


def _scope(practice_id: uuid.UUID, location_id: uuid.UUID) -> StaffContext:
    """Location scope for public/unauthenticated waitlist operations."""
    return StaffContext(user=None, practice_id=practice_id, location_id=location_id)  # type: ignore[arg-type]


async def _get_provider(
    db: AsyncSession, practice_id: uuid.UUID, location_id: uuid.UUID, provider_id: uuid.UUID
) -> Provider | None:
    provider = await db.get(Provider, provider_id)
    if provider is None or provider.practice_id != practice_id or provider.location_id != location_id:
        return None
    return provider


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


def _format_slot_line(slot: WaitlistRequestSlot, provider_name: str, operatory_name: str | None) -> str:
    when = slot.starts_at.strftime("%A, %B %-d at %-I:%M %p")
    suffix = f" with {provider_name}"
    if operatory_name:
        suffix += f" in {operatory_name}"
    return f"{when}{suffix}"


def _message_body(
    *,
    template_type: str,
    patient_first_name: str,
    slots: list[WaitlistRequestSlot],
    provider_names: dict[uuid.UUID, str],
    operatory_names: dict[uuid.UUID | None, str | None],
    booking_url: str,
) -> str:
    slot_lines = [
        _format_slot_line(s, provider_names.get(s.provider_id, "your provider"), operatory_names.get(s.operatory_id))
        for s in slots
    ]
    if template_type == WaitlistTemplateType.CONTINUING_CARE.value:
        intro = (
            f"Hi {patient_first_name} — you're due for continuing care and we have earlier openings available."
        )
    else:
        intro = f"Hi {patient_first_name} — an earlier appointment time just opened up at our office."
    if len(slot_lines) == 1:
        slots_text = slot_lines[0]
    else:
        slots_text = "\n".join(f"• {line}" for line in slot_lines)
    return (
        f"{intro}\n\n{slots_text}\n\nBook now (one tap, no forms needed): {booking_url}"
    )


async def _provider_names(db: AsyncSession, ctx: StaffContext, slots: list[WaitlistRequestSlot]) -> dict[uuid.UUID, str]:
    out: dict[uuid.UUID, str] = {}
    for slot in slots:
        if slot.provider_id in out:
            continue
        provider = await providers_service.get_provider(db, ctx, slot.provider_id)
        out[slot.provider_id] = provider.name if provider else "Provider"
    return out


async def _operatory_names(
    db: AsyncSession, ctx: StaffContext, slots: list[WaitlistRequestSlot]
) -> dict[uuid.UUID | None, str | None]:
    out: dict[uuid.UUID | None, str | None] = {None: None}
    for slot in slots:
        if slot.operatory_id in out:
            continue
        if slot.operatory_id is None:
            out[None] = None
            continue
        operatory = await providers_service.get_operatory(db, ctx, slot.operatory_id)
        out[slot.operatory_id] = operatory.name if operatory else None
    return out


async def _notify_patient(
    db: AsyncSession,
    ctx: StaffContext,
    *,
    patient: Patient,
    wp: WaitlistRequestPatient,
    template_type: str,
    slots: list[WaitlistRequestSlot],
    provider_names: dict[uuid.UUID, str],
    operatory_names: dict[uuid.UUID | None, str | None],
    booking_base_url: str,
    now: datetime,
) -> None:
    booking_url = f"{booking_base_url.rstrip('/')}/waitlist/{wp.booking_token}"
    body = _message_body(
        template_type=template_type,
        patient_first_name=patient.first_name,
        slots=slots,
        provider_names=provider_names,
        operatory_names=operatory_names,
        booking_url=booking_url,
    )
    thread = await _get_or_create_thread(db, ctx, patient.id)
    # New messages restore archived conversations to the inbox
    thread.archived = False
    thread.unread = False
    db.add(
        Message(
            thread_id=thread.id,
            direction="outbound",
            body=body,
            channel=MessageChannel.SMS,
            sent_at=now,
            delivery_status="delivered",
        )
    )
    wp.notified_at = now
    wp.scheduled_notify_at = None


async def _process_scheduled_notifications(db: AsyncSession, ctx: StaffContext, request: WaitlistRequest) -> None:
    if request.status != WaitlistRequestStatus.SENT:
        return
    open_slots = await _open_slots(db, request.id)
    if not open_slots:
        return

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(WaitlistRequestPatient, Patient)
        .join(Patient, Patient.id == WaitlistRequestPatient.patient_id)
        .where(
            WaitlistRequestPatient.waitlist_request_id == request.id,
            WaitlistRequestPatient.notified_at.is_(None),
            WaitlistRequestPatient.scheduled_notify_at.is_not(None),
            WaitlistRequestPatient.scheduled_notify_at <= now,
        )
        .order_by(WaitlistRequestPatient.scheduled_notify_at)
        .limit(SMART_SEND_BATCH_SIZE)
    )
    pending = list(result.all())
    if not pending:
        return

    slots = await get_slots(db, request.id)
    provider_names = await _provider_names(db, ctx, slots)
    operatory_names = await _operatory_names(db, ctx, slots)
    practice = await db.get(Practice, ctx.practice_id)
    booking_base = settings.frontend_url

    for wp, patient in pending:
        await _notify_patient(
            db,
            ctx,
            patient=patient,
            wp=wp,
            template_type=request.template_type,
            slots=open_slots,
            provider_names=provider_names,
            operatory_names=operatory_names,
            booking_base_url=booking_base or settings.frontend_url,
            now=now,
        )

    # Schedule next batch if more patients remain.
    remaining = await db.execute(
        select(WaitlistRequestPatient).where(
            WaitlistRequestPatient.waitlist_request_id == request.id,
            WaitlistRequestPatient.notified_at.is_(None),
            WaitlistRequestPatient.scheduled_notify_at.is_(None),
        )
    )
    unscheduled = list(remaining.scalars().all())
    next_at = now + timedelta(minutes=SMART_SEND_INTERVAL_MINUTES)
    for wp in unscheduled[:SMART_SEND_BATCH_SIZE]:
        wp.scheduled_notify_at = next_at
    await db.flush()


async def create_and_send_request(
    db: AsyncSession,
    ctx: StaffContext,
    data: WaitlistRequestCreate,
    *,
    booking_base_url: str | None = None,
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

    request = WaitlistRequest(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        template_type=data.template_type,
    )
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

    now = datetime.now(timezone.utc)
    base = booking_base_url or settings.frontend_url
    patient_rows: list[tuple[WaitlistRequestPatient, Patient]] = []
    for patient_id in data.patient_ids:
        patient = await db.get(Patient, patient_id)
        if patient is None or patient.practice_id != ctx.practice_id:
            raise ValueError(f"Patient {patient_id} not found")
        wp = WaitlistRequestPatient(
            waitlist_request_id=request.id,
            patient_id=patient_id,
            booking_token=uuid.uuid4(),
        )
        db.add(wp)
        patient_rows.append((wp, patient))
    await db.flush()

    provider_names = await _provider_names(db, ctx, slot_rows)
    operatory_names = await _operatory_names(db, ctx, slot_rows)

    use_smart_send = len(patient_rows) > SMART_SEND_THRESHOLD
    immediate_count = SMART_SEND_BATCH_SIZE if use_smart_send else len(patient_rows)

    for idx, (wp, patient) in enumerate(patient_rows):
        if idx < immediate_count:
            await _notify_patient(
                db,
                ctx,
                patient=patient,
                wp=wp,
                template_type=data.template_type,
                slots=slot_rows,
                provider_names=provider_names,
                operatory_names=operatory_names,
                booking_base_url=base,
                now=now,
            )
        elif use_smart_send:
            batch_num = (idx - immediate_count) // SMART_SEND_BATCH_SIZE + 1
            wp.scheduled_notify_at = now + timedelta(minutes=SMART_SEND_INTERVAL_MINUTES * batch_num)

    await db.flush()
    return request


async def list_requests(db: AsyncSession, ctx: StaffContext) -> list[WaitlistRequest]:
    result = await db.execute(
        select(WaitlistRequest)
        .where(WaitlistRequest.practice_id == ctx.practice_id, WaitlistRequest.location_id == ctx.location_id)
        .order_by(WaitlistRequest.created_at.desc())
    )
    requests = list(result.scalars().all())
    for request in requests:
        await _process_scheduled_notifications(db, ctx, request)
    return requests


async def get_request(db: AsyncSession, ctx: StaffContext, request_id: uuid.UUID) -> WaitlistRequest | None:
    request = await db.get(WaitlistRequest, request_id)
    if request is None or request.practice_id != ctx.practice_id or request.location_id != ctx.location_id:
        return None
    await _process_scheduled_notifications(db, ctx, request)
    return request


async def get_slots(db: AsyncSession, request_id: uuid.UUID) -> list[WaitlistRequestSlot]:
    result = await db.execute(
        select(WaitlistRequestSlot).where(WaitlistRequestSlot.waitlist_request_id == request_id)
    )
    return list(result.scalars().all())


async def _open_slots(db: AsyncSession, request_id: uuid.UUID) -> list[WaitlistRequestSlot]:
    now = datetime.now(timezone.utc)
    slots = await get_slots(db, request_id)
    return [
        s
        for s in slots
        if s.claimed_by_patient_id is None
        and s.cancelled_at is None
        and now <= s.starts_at - timedelta(minutes=EXPIRY_BUFFER_MINUTES)
    ]


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
    return await _claim_slot_internal(db, ctx, request, slot, patient_id, ehr_sync=True)


async def claim_slot_public(
    db: AsyncSession, wp: WaitlistRequestPatient, slot: WaitlistRequestSlot
) -> WaitlistRequestSlot:
    request = await db.get(WaitlistRequest, wp.waitlist_request_id)
    if request is None:
        raise ValueError("Waitlist request not found")
    ctx = _scope(request.practice_id, request.location_id)
    return await _claim_slot_internal(db, ctx, request, slot, wp.patient_id, ehr_sync=True)


async def _claim_slot_internal(
    db: AsyncSession,
    ctx: StaffContext,
    request: WaitlistRequest,
    slot: WaitlistRequestSlot,
    patient_id: uuid.UUID,
    *,
    ehr_sync: bool,
) -> WaitlistRequestSlot:
    if request.status == WaitlistRequestStatus.CANCELLED:
        raise ValueError("This waitlist request has been cancelled")
    if slot.cancelled_at is not None:
        raise ValueError("This slot has been cancelled")
    if slot.claimed_by_patient_id is not None:
        if slot.claimed_by_patient_id == patient_id:
            return slot
        raise ValueError("The time you have selected is no longer available")
    now = datetime.now(timezone.utc)
    if now > slot.starts_at - timedelta(minutes=EXPIRY_BUFFER_MINUTES):
        raise ValueError("We're sorry, but this slot is no longer available")

    patient = await db.get(Patient, patient_id)
    if patient is None or patient.practice_id != ctx.practice_id:
        raise ValueError("Patient not found")
    provider = await providers_service.get_provider(db, ctx, slot.provider_id)
    if provider is None:
        raise ValueError("Provider not found")

    operatory_name = ""
    if slot.operatory_id is not None:
        operatory = await providers_service.get_operatory(db, ctx, slot.operatory_id)
        if operatory is not None:
            operatory_name = operatory.name

    mapping_context = appointment_rules_service.MappingContext(
        provider_name=provider.name,
        operatory=operatory_name,
    )
    appt_type, meta = await appointment_rules_service.resolve_appointment_type(
        db,
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        mapping_context=mapping_context,
        source="waitlist",
    )

    duration_minutes = max(5, int((slot.ends_at - slot.starts_at).total_seconds() // 60))
    if appt_type is not None:
        duration_minutes = appt_type.duration_minutes

    appointment = Appointment(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        patient_id=patient_id,
        provider_name=provider.name,
        appointment_type=appt_type.name if appt_type else "Waitlist",
        appointment_type_def_id=appt_type.id if appt_type else None,
        starts_at=slot.starts_at,
        duration_minutes=duration_minutes,
        status=AppointmentStatus.UNCONFIRMED,
        meta={**meta, "waitlist_request_id": str(request.id), "waitlist_slot_id": str(slot.id)},
    )
    db.add(appointment)
    await db.flush()

    activity_meta = {"appointment_id": str(appointment.id), **meta}
    if ehr_sync and not patient.ehr_patient_id:
        activity_meta["ehr_sync_failed"] = True
        activity_title = (
            f"{patient.first_name} {patient.last_name} accepted a waitlist slot for "
            f"{slot.starts_at.strftime('%a, %B %-d %I:%M %p')} with {provider.name}"
        )
        await staff_service._log_activity(  # noqa: SLF001
            db,
            patient_id=patient_id,
            activity_type=ActivityType.APPOINTMENT,
            title=activity_title,
            meta={
                **activity_meta,
                "alert": "We were unable to create the appointment. Please manually create it in your health record system.",
            },
        )
    else:
        await staff_service._log_activity(  # noqa: SLF001
            db,
            patient_id=patient_id,
            activity_type=ActivityType.APPOINTMENT,
            title=f"Waitlist slot claimed — {appointment.appointment_type}",
            meta=activity_meta,
        )

    if ctx.user is not None:
        await staff_service.evaluate_automatic_form_requests(
            db,
            practice_id=ctx.practice_id,
            location_id=ctx.location_id,
            appointment=appointment,
            ctx=ctx,
        )

    slot.claimed_by_patient_id = patient_id
    slot.claimed_at = now
    slot.created_appointment_id = appointment.id
    await db.flush()
    return slot


async def get_public_waitlist(db: AsyncSession, token: uuid.UUID) -> dict | None:
    result = await db.execute(
        select(WaitlistRequestPatient, WaitlistRequest, Patient, Practice, Location)
        .join(WaitlistRequest, WaitlistRequest.id == WaitlistRequestPatient.waitlist_request_id)
        .join(Patient, Patient.id == WaitlistRequestPatient.patient_id)
        .join(Practice, Practice.id == WaitlistRequest.practice_id)
        .join(Location, Location.id == WaitlistRequest.location_id)
        .where(WaitlistRequestPatient.booking_token == token)
    )
    row = result.first()
    if row is None:
        return None
    wp, request, patient, practice, location = row
    if request.status == WaitlistRequestStatus.CANCELLED:
        return None

    open_slots = await _open_slots(db, request.id)
    ctx = _scope(request.practice_id, request.location_id)
    provider_names = await _provider_names(db, ctx, open_slots)
    operatory_names = await _operatory_names(db, ctx, open_slots)

    return {
        "practice_name": practice.name,
        "location_name": location.name,
        "patient_first_name": patient.first_name,
        "booking_redirect_slug": practice_slug(practice.name),
        "slots": [
            {
                "id": s.id,
                "starts_at": s.starts_at,
                "ends_at": s.ends_at,
                "provider_name": provider_names.get(s.provider_id, "Provider"),
                "operatory_name": operatory_names.get(s.operatory_id),
                "label": s.starts_at.strftime("%A, %B %-d at %-I:%M %p"),
            }
            for s in open_slots
        ],
        "wp": wp,
        "request": request,
    }


async def _patients_with_future_appointments(
    db: AsyncSession, ctx: StaffContext, *, after: datetime | None = None
) -> set[uuid.UUID]:
    now = after or datetime.now(timezone.utc)
    result = await db.execute(
        select(Appointment.patient_id).where(
            Appointment.practice_id == ctx.practice_id,
            Appointment.location_id == ctx.location_id,
            Appointment.starts_at > now,
            Appointment.status != AppointmentStatus.CANCELLED,
        )
    )
    return {row[0] for row in result.all()}


async def _recently_notified_patients(
    db: AsyncSession, ctx: StaffContext, exclude_recent_days: int
) -> set[uuid.UUID]:
    if exclude_recent_days <= 0:
        return set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=exclude_recent_days)
    result = await db.execute(
        select(WaitlistRequestPatient.patient_id)
        .join(WaitlistRequest, WaitlistRequest.id == WaitlistRequestPatient.waitlist_request_id)
        .where(
            WaitlistRequest.practice_id == ctx.practice_id,
            WaitlistRequest.location_id == ctx.location_id,
            WaitlistRequestPatient.notified_at.is_not(None),
            WaitlistRequestPatient.notified_at >= cutoff,
        )
    )
    return {row[0] for row in result.all()}


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

    has_future = await _patients_with_future_appointments(db, ctx)
    recent_ids = await _recently_notified_patients(db, ctx, exclude_recent_days)

    seen: set[uuid.UUID] = set()
    out: list[tuple[Patient, Appointment]] = []
    for appt, patient in rows:
        if patient.id in has_future or patient.id in recent_ids or patient.id in seen:
            continue
        # Exclude patients with a non-cancelled appointment within 6 months after the original date.
        six_months_out = appt.starts_at + timedelta(days=183)
        conflict = await db.execute(
            select(Appointment.id).where(
                Appointment.patient_id == patient.id,
                Appointment.practice_id == ctx.practice_id,
                Appointment.location_id == ctx.location_id,
                Appointment.status != AppointmentStatus.CANCELLED,
                Appointment.starts_at > appt.starts_at,
                Appointment.starts_at <= six_months_out,
            ).limit(1)
        )
        if conflict.scalar_one_or_none() is not None:
            continue
        seen.add(patient.id)
        out.append((patient, appt))
    return out


async def search_asap(
    db: AsyncSession,
    ctx: StaffContext,
    *,
    provider_id: uuid.UUID | None,
    operatory_id: uuid.UUID | None,
    appointment_type_id: uuid.UUID | None,
    duration_minutes: int | None,
    exclude_recent_days: int,
) -> list[tuple[Patient, Appointment]]:
    now = datetime.now(timezone.utc)
    conditions = [
        Appointment.practice_id == ctx.practice_id,
        Appointment.location_id == ctx.location_id,
        Appointment.starts_at > now,
        Appointment.status != AppointmentStatus.CANCELLED,
    ]
    if appointment_type_id is not None:
        conditions.append(Appointment.appointment_type_def_id == appointment_type_id)
    if duration_minutes is not None:
        conditions.append(Appointment.duration_minutes == duration_minutes)

    result = await db.execute(
        select(Appointment, Patient)
        .join(Patient, Patient.id == Appointment.patient_id)
        .where(and_(*conditions))
        .order_by(Appointment.starts_at)
    )
    rows = result.all()

    # ASAP patients already have a future appointment (that's the ASAP list).
    # Unlike missed/continuing-care, do not exclude them for having upcoming visits.
    recent_ids = await _recently_notified_patients(db, ctx, exclude_recent_days)

    provider = None
    if provider_id is not None:
        provider = await providers_service.get_provider(db, ctx, provider_id)

    seen: set[uuid.UUID] = set()
    out: list[tuple[Patient, Appointment]] = []
    for appt, patient in rows:
        if not (appt.meta or {}).get("asap"):
            continue
        if patient.id in recent_ids or patient.id in seen:
            continue
        if provider is not None and appt.provider_name != provider.name:
            continue
        if operatory_id is not None:
            op_name = (appt.meta or {}).get("operatory", "")
            operatory = await providers_service.get_operatory(db, ctx, operatory_id)
            if operatory is not None and op_name and op_name != operatory.name:
                continue
        seen.add(patient.id)
        out.append((patient, appt))
    return out


async def search_continuing_care(
    db: AsyncSession,
    ctx: StaffContext,
    *,
    recall_type: str | None,
    start_date: date | None,
    end_date: date | None,
    exclude_recent_days: int,
) -> list[Patient]:
    if start_date is None or end_date is None:
        raise ValueError("Select a date range for continuing care patients")

    result = await db.execute(
        select(Patient).where(
            Patient.practice_id == ctx.practice_id,
            Patient.location_id == ctx.location_id,
            Patient.archived.is_(False),
        )
    )
    patients = list(result.scalars().all())
    has_future = await _patients_with_future_appointments(db, ctx)
    recent_ids = await _recently_notified_patients(db, ctx, exclude_recent_days)

    out: list[Patient] = []
    for patient in patients:
        recall = (patient.meta or {}).get("recall") or {}
        due_raw = recall.get("due_date")
        if not due_raw:
            continue
        try:
            due_date = date.fromisoformat(str(due_raw)[:10])
        except ValueError:
            continue
        if due_date < start_date or due_date > end_date:
            continue
        if recall_type and str(recall.get("type", "")).lower() != recall_type.lower():
            continue
        if patient.id in has_future or patient.id in recent_ids:
            continue
        out.append(patient)
    return out
