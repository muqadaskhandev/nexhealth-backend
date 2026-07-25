"""Staff workflow business logic."""
from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core import security
from app.core.staff_context import StaffContext
from app.models.appointment_types import AppointmentTypeDef
from app.models.location import Location
from app.models.staff import (
    ActivityType,
    Appointment,
    AppointmentStatus,
    FormAccessToken,
    FormPacket,
    FormRequest,
    FormRequestStatus,
    FormSubmission,
    FormTemplate,
    FormsStatus,
    InsuranceStatus,
    Message,
    MessageChannel,
    MessageThread,
    Patient,
    PatientActivity,
    PaymentLink,
    PaymentStatus,
    WaitlistEntry,
    WaitlistStatus,
)
from app.schemas.staff import (
    AppointmentCreate,
    AppointmentUpdate,
    FormPacketCreate,
    FormPacketUpdate,
    FormTemplateCreate,
    FormTemplateUpdate,
    PatientCreate,
    PatientUpdate,
    PaymentLinkCreate,
    SendFormRequest,
    SendMessageRequest,
    WaitlistCreate,
)
from app.services import form_upload_storage

FORM_FIELD_TYPES = {
    "text", "textarea", "email", "number", "phone",
    "checkbox", "select_boxes", "dropdown", "radio",
    "date", "date_entry", "address", "file", "signature",
    "insurance", "preferred_language", "payment",
    "content", "location_logo",
}

RULE_PATIENT_STATUSES = {"any", "new", "existing"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


FORM_REQUEST_EXPIRY_GRACE_HOURS = 12


def _compute_expires_at(amount: int, unit: str, from_dt: datetime) -> datetime:
    if unit == "weeks":
        return from_dt + timedelta(weeks=amount)
    if unit == "months":
        return from_dt + timedelta(days=30 * amount)
    return from_dt + timedelta(days=amount)


async def create_form_access_token(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID,
    location_id: uuid.UUID,
    patient_id: uuid.UUID,
    expires_at: datetime,
) -> str:
    """Creates an opaque link token for the patient forms portal and returns the raw value (never stored)."""
    raw = security.generate_opaque_token()
    db.add(
        FormAccessToken(
            token_hash=security.hash_token(raw),
            practice_id=practice_id,
            location_id=location_id,
            patient_id=patient_id,
            expires_at=expires_at,
        )
    )
    await db.flush()
    return raw


async def _log_activity(
    db: AsyncSession,
    *,
    patient_id: uuid.UUID,
    activity_type: ActivityType,
    title: str,
    body: str = "",
    meta: dict | None = None,
) -> None:
    db.add(
        PatientActivity(
            patient_id=patient_id,
            activity_type=activity_type,
            title=title,
            body=body,
            meta=meta or {},
        )
    )


# ── Patients ─────────────────────────────────────────────────────────────────
async def list_patients(
    db: AsyncSession,
    ctx: StaffContext,
    *,
    q: str = "",
    archived: bool = False,
    all_locations: bool = False,
) -> list[Patient]:
    stmt = select(Patient).where(
        Patient.practice_id == ctx.practice_id,
        Patient.archived == archived,
    )
    if not all_locations:
        stmt = stmt.where(Patient.location_id == ctx.location_id)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Patient.first_name).like(like),
                func.lower(Patient.last_name).like(like),
                func.lower(Patient.email).like(like),
                Patient.phone.like(like),
            )
        )
    stmt = stmt.order_by(Patient.last_name, Patient.first_name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_patient(db: AsyncSession, ctx: StaffContext, patient_id: uuid.UUID) -> Patient | None:
    result = await db.execute(
        select(Patient).where(
            Patient.id == patient_id,
            Patient.practice_id == ctx.practice_id,
            Patient.location_id == ctx.location_id,
        )
    )
    return result.scalar_one_or_none()


async def create_patient(db: AsyncSession, ctx: StaffContext, data: PatientCreate) -> Patient:
    patient = Patient(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        first_name=data.first_name.strip(),
        last_name=data.last_name.strip(),
        preferred_name=data.preferred_name,
        dob=data.dob,
        gender=data.gender,
        email=str(data.email).strip().lower() if data.email else "",
        phone=data.phone,
        address=data.address,
        language=data.language,
        provider_name=data.provider_name,
        synced=False,
        insurance_data=data.insurance_data or {"status": "unknown", "name": "Unknown"},
        notification_prefs=data.notification_prefs or {},
    )
    db.add(patient)
    await db.flush()
    await _log_activity(
        db,
        patient_id=patient.id,
        activity_type=ActivityType.NOTE,
        title="Patient record created",
    )
    return patient


async def update_patient(
    db: AsyncSession, ctx: StaffContext, patient: Patient, data: PatientUpdate
) -> Patient:
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "email" and value is not None:
            value = str(value).strip().lower()
        setattr(patient, field, value)
    await db.flush()
    return patient


async def find_duplicate_patients(db: AsyncSession, ctx: StaffContext) -> list[list[Patient]]:
    patients = await list_patients(db, ctx)
    groups: dict[str, list[Patient]] = {}
    for p in patients:
        if p.email:
            groups.setdefault(f"email:{p.email.lower()}", []).append(p)
        phone_key = "".join(c for c in p.phone if c.isdigit())
        if phone_key:
            groups.setdefault(f"phone:{phone_key}", []).append(p)
    return [g for g in groups.values() if len(g) > 1]


async def merge_patients(
    db: AsyncSession, ctx: StaffContext, *, keep_id: uuid.UUID, merge_id: uuid.UUID
) -> Patient:
    keep = await get_patient(db, ctx, keep_id)
    merge = await get_patient(db, ctx, merge_id)
    if keep is None or merge is None:
        raise ValueError("Patient not found")
    merge.archived = True
    await _log_activity(
        db,
        patient_id=keep.id,
        activity_type=ActivityType.NOTE,
        title=f"Merged duplicate record {merge.first_name} {merge.last_name}",
    )
    await db.flush()
    return keep


async def list_patient_activity(
    db: AsyncSession, patient_id: uuid.UUID
) -> list[PatientActivity]:
    result = await db.execute(
        select(PatientActivity)
        .where(PatientActivity.patient_id == patient_id)
        .order_by(PatientActivity.created_at.desc())
    )
    return list(result.scalars().all())


# ── Appointments ─────────────────────────────────────────────────────────────
async def list_appointments(
    db: AsyncSession,
    ctx: StaffContext,
    *,
    day: datetime | None = None,
    patient_id: uuid.UUID | None = None,
) -> list[tuple[Appointment, Patient]]:
    stmt = (
        select(Appointment, Patient)
        .join(Patient, Patient.id == Appointment.patient_id)
        .where(
            Appointment.practice_id == ctx.practice_id,
            Appointment.location_id == ctx.location_id,
        )
    )
    if patient_id:
        stmt = stmt.where(Appointment.patient_id == patient_id)
    elif day:
        start = datetime.combine(day.date(), time.min, tzinfo=timezone.utc)
        end = datetime.combine(day.date(), time.max, tzinfo=timezone.utc)
        stmt = stmt.where(Appointment.starts_at >= start, Appointment.starts_at <= end)
    stmt = stmt.order_by(Appointment.starts_at)
    result = await db.execute(stmt)
    return list(result.all())


async def create_appointment(
    db: AsyncSession, ctx: StaffContext, data: AppointmentCreate
) -> Appointment:
    patient = await get_patient(db, ctx, data.patient_id)
    if patient is None:
        raise ValueError("Patient not found")
    appt = Appointment(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        patient_id=data.patient_id,
        provider_name=data.provider_name,
        appointment_type=data.appointment_type,
        starts_at=data.starts_at,
        duration_minutes=data.duration_minutes,
        status=AppointmentStatus(data.status),
    )
    db.add(appt)
    await db.flush()
    await _log_activity(
        db,
        patient_id=data.patient_id,
        activity_type=ActivityType.APPOINTMENT,
        title=f"Appointment scheduled — {data.appointment_type}",
        meta={"appointment_id": str(appt.id)},
    )
    await evaluate_automatic_form_requests(db, ctx, appt)
    return appt


async def update_appointment(
    db: AsyncSession, ctx: StaffContext, appt_id: uuid.UUID, data: AppointmentUpdate
) -> Appointment | None:
    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appt_id,
            Appointment.practice_id == ctx.practice_id,
            Appointment.location_id == ctx.location_id,
        )
    )
    appt = result.scalar_one_or_none()
    if appt is None:
        return None
    payload = data.model_dump(exclude_unset=True)
    if "status" in payload:
        appt.status = AppointmentStatus(payload["status"])
        del payload["status"]
    if "insurance_status" in payload:
        appt.insurance_status = InsuranceStatus(payload["insurance_status"])
        del payload["insurance_status"]
    if "forms_status" in payload:
        appt.forms_status = FormsStatus(payload["forms_status"])
        del payload["forms_status"]
    for k, v in payload.items():
        setattr(appt, k, v)
    await db.flush()
    return appt


# ── Waitlist ─────────────────────────────────────────────────────────────────
async def list_waitlist(db: AsyncSession, ctx: StaffContext) -> list[tuple[WaitlistEntry, Patient]]:
    result = await db.execute(
        select(WaitlistEntry, Patient)
        .join(Patient, Patient.id == WaitlistEntry.patient_id)
        .where(
            WaitlistEntry.practice_id == ctx.practice_id,
            WaitlistEntry.location_id == ctx.location_id,
            WaitlistEntry.status == WaitlistStatus.WAITING,
        )
        .order_by(WaitlistEntry.created_at)
    )
    return list(result.all())


async def add_waitlist(
    db: AsyncSession, ctx: StaffContext, data: WaitlistCreate
) -> WaitlistEntry:
    entry = WaitlistEntry(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        patient_id=data.patient_id,
        provider_name=data.provider_name,
        appointment_type=data.appointment_type,
        notes=data.notes,
    )
    db.add(entry)
    await db.flush()
    return entry


# ── Forms ────────────────────────────────────────────────────────────────────
def _validate_form_fields(data: FormTemplateCreate | FormTemplateUpdate) -> None:
    field_ids = {f.id for f in data.fields}
    for field in data.fields:
        if not field.label.strip():
            raise ValueError("Every field needs a label")
        if field.type not in FORM_FIELD_TYPES:
            raise ValueError(f"Unknown field type: {field.type}")
        if not (1 <= field.page <= data.page_count):
            raise ValueError(f"Field '{field.label}' is on a page outside the form's page count")
        if field.min_length is not None and field.max_length is not None and field.min_length > field.max_length:
            raise ValueError(f"Field '{field.label}' has a minimum length greater than its maximum length")
        if field.conditional_field_id:
            if field.conditional_field_id == field.id:
                raise ValueError(f"Field '{field.label}' can't be conditional on itself")
            if field.conditional_field_id not in field_ids:
                raise ValueError(f"Field '{field.label}' references a condition field that doesn't exist")


def _validate_automation_rule(data: FormTemplateCreate | FormTemplateUpdate) -> None:
    if data.rule_patient_status not in RULE_PATIENT_STATUSES:
        raise ValueError(f"Unknown patient status rule: {data.rule_patient_status}")
    if data.rule_min_age is not None and data.rule_max_age is not None and data.rule_min_age > data.rule_max_age:
        raise ValueError("Minimum age can't be greater than maximum age")


async def list_form_templates(
    db: AsyncSession, ctx: StaffContext, *, archived: bool = False
) -> list[FormTemplate]:
    archived_filter = FormTemplate.archived_at.isnot(None) if archived else FormTemplate.archived_at.is_(None)
    result = await db.execute(
        select(FormTemplate)
        .where(
            FormTemplate.practice_id == ctx.practice_id,
            FormTemplate.location_id == ctx.location_id,
            archived_filter,
        )
        .order_by(FormTemplate.name)
    )
    return list(result.scalars().all())


async def get_form_template(db: AsyncSession, ctx: StaffContext, template_id: uuid.UUID) -> FormTemplate | None:
    tpl = await db.get(FormTemplate, template_id)
    if tpl is None or tpl.practice_id != ctx.practice_id or tpl.location_id != ctx.location_id:
        return None
    return tpl


async def create_form_template(db: AsyncSession, ctx: StaffContext, data: FormTemplateCreate) -> FormTemplate:
    if not data.name.strip():
        raise ValueError("Name is required")
    _validate_form_fields(data)
    _validate_automation_rule(data)
    tpl = FormTemplate(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        name=data.name.strip(),
        form_type=data.form_type,
        display_type=data.display_type,
        fields=[f.model_dump() for f in data.fields],
        page_count=data.page_count,
        source="build",
        status="active",
        send_automatically=data.send_automatically,
        rule_patient_status=data.rule_patient_status,
        rule_frequency_months=data.rule_frequency_months,
        rule_min_age=data.rule_min_age,
        rule_max_age=data.rule_max_age,
        rule_appointment_type_ids=[str(i) for i in data.rule_appointment_type_ids],
    )
    db.add(tpl)
    await db.flush()
    return tpl


async def update_form_template(
    db: AsyncSession, template: FormTemplate, data: FormTemplateUpdate
) -> FormTemplate:
    if not data.name.strip():
        raise ValueError("Name is required")
    _validate_form_fields(data)
    _validate_automation_rule(data)
    template.name = data.name.strip()
    template.form_type = data.form_type
    template.display_type = data.display_type
    template.fields = [f.model_dump() for f in data.fields]
    template.page_count = data.page_count
    template.send_automatically = data.send_automatically
    template.rule_patient_status = data.rule_patient_status
    template.rule_frequency_months = data.rule_frequency_months
    template.rule_min_age = data.rule_min_age
    template.rule_max_age = data.rule_max_age
    template.rule_appointment_type_ids = [str(i) for i in data.rule_appointment_type_ids]
    await db.flush()
    return template


async def create_digitized_form_template(
    db: AsyncSession, ctx: StaffContext, name: str, notes: str, upload
) -> FormTemplate:
    if not name.strip():
        raise ValueError("Name is required")
    file_url = await form_upload_storage.save_form_upload(upload)
    tpl = FormTemplate(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        name=name.strip(),
        source="digitize",
        status="digitizing",
        digitize_notes=notes,
        uploaded_file_url=file_url,
        fields=[],
    )
    db.add(tpl)
    await db.flush()
    return tpl


async def duplicate_form_template(db: AsyncSession, ctx: StaffContext, template: FormTemplate) -> FormTemplate:
    copy = FormTemplate(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        name=f"{template.name} (copy)",
        form_type=template.form_type,
        source=template.source,
        status=template.status,
        display_type=template.display_type,
        fields=template.fields,
        page_count=template.page_count,
        uploaded_file_url=template.uploaded_file_url,
        digitize_notes=template.digitize_notes,
    )
    db.add(copy)
    await db.flush()
    return copy


async def copy_form_templates(
    db: AsyncSession, ctx: StaffContext, template_ids: list[uuid.UUID], location_ids: list[uuid.UUID]
) -> int:
    result = await db.execute(
        select(FormTemplate).where(
            FormTemplate.id.in_(template_ids),
            FormTemplate.practice_id == ctx.practice_id,
            FormTemplate.location_id == ctx.location_id,
        )
    )
    sources = result.scalars().all()
    if len(sources) != len(set(template_ids)):
        raise ValueError("Some forms could not be found in your current location")

    target_locations = [lid for lid in dict.fromkeys(location_ids) if lid != ctx.location_id]
    if not target_locations:
        raise ValueError("Select at least one other location to copy to")

    copied = 0
    for loc_id in target_locations:
        for src in sources:
            existing_result = await db.execute(
                select(FormTemplate).where(
                    FormTemplate.practice_id == ctx.practice_id,
                    FormTemplate.location_id == loc_id,
                    FormTemplate.name == src.name,
                )
            )
            existing = existing_result.scalar_one_or_none()
            if existing:
                existing.form_type = src.form_type
                existing.source = src.source
                existing.status = src.status
                existing.display_type = src.display_type
                existing.fields = src.fields
                existing.page_count = src.page_count
                existing.uploaded_file_url = src.uploaded_file_url
                existing.digitize_notes = src.digitize_notes
            else:
                db.add(FormTemplate(
                    practice_id=ctx.practice_id,
                    location_id=loc_id,
                    name=src.name,
                    form_type=src.form_type,
                    source=src.source,
                    status=src.status,
                    display_type=src.display_type,
                    fields=src.fields,
                    page_count=src.page_count,
                    uploaded_file_url=src.uploaded_file_url,
                    digitize_notes=src.digitize_notes,
                ))
            copied += 1
    await db.flush()
    return copied


async def archive_form_template(db: AsyncSession, template: FormTemplate) -> FormTemplate:
    template.archived_at = _now()
    await db.flush()
    return template


async def unarchive_form_template(db: AsyncSession, template: FormTemplate) -> FormTemplate:
    template.archived_at = None
    await db.flush()
    return template


async def _validate_packet_forms(
    db: AsyncSession, practice_id: uuid.UUID, location_id: uuid.UUID, form_template_ids: list[uuid.UUID]
) -> None:
    result = await db.execute(
        select(FormTemplate.id).where(
            FormTemplate.id.in_(form_template_ids),
            FormTemplate.practice_id == practice_id,
            FormTemplate.location_id == location_id,
        )
    )
    found = {row[0] for row in result.all()}
    if found != set(form_template_ids):
        raise ValueError("Some forms could not be found in your current location")


async def list_form_packets(db: AsyncSession, ctx: StaffContext) -> list[FormPacket]:
    result = await db.execute(
        select(FormPacket)
        .where(FormPacket.practice_id == ctx.practice_id, FormPacket.location_id == ctx.location_id)
        .order_by(FormPacket.name)
    )
    return list(result.scalars().all())


async def get_form_packet(db: AsyncSession, ctx: StaffContext, packet_id: uuid.UUID) -> FormPacket | None:
    packet = await db.get(FormPacket, packet_id)
    if packet is None or packet.practice_id != ctx.practice_id or packet.location_id != ctx.location_id:
        return None
    return packet


async def create_form_packet(db: AsyncSession, ctx: StaffContext, data: FormPacketCreate) -> FormPacket:
    if not data.name.strip():
        raise ValueError("Name is required")
    await _validate_packet_forms(db, ctx.practice_id, ctx.location_id, data.form_template_ids)
    packet = FormPacket(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        name=data.name.strip(),
        form_template_ids=[str(i) for i in data.form_template_ids],
    )
    db.add(packet)
    await db.flush()
    return packet


async def update_form_packet(db: AsyncSession, packet: FormPacket, data: FormPacketUpdate) -> FormPacket:
    if not data.name.strip():
        raise ValueError("Name is required")
    await _validate_packet_forms(db, packet.practice_id, packet.location_id, data.form_template_ids)
    packet.name = data.name.strip()
    packet.form_template_ids = [str(i) for i in data.form_template_ids]
    await db.flush()
    return packet


async def delete_form_packet(db: AsyncSession, packet: FormPacket) -> None:
    await db.delete(packet)
    await db.flush()


async def list_form_submissions(
    db: AsyncSession, ctx: StaffContext
) -> list[tuple[FormSubmission, Patient]]:
    result = await db.execute(
        select(FormSubmission, Patient)
        .join(Patient, Patient.id == FormSubmission.patient_id)
        .where(Patient.practice_id == ctx.practice_id, Patient.location_id == ctx.location_id)
        .order_by(FormSubmission.submitted_at.desc())
    )
    return list(result.all())


async def list_frequent_form_templates(
    db: AsyncSession, ctx: StaffContext, *, limit: int = 3
) -> list[FormTemplate]:
    result = await db.execute(
        select(FormTemplate)
        .join(FormRequest, FormRequest.form_template_id == FormTemplate.id)
        .where(
            FormTemplate.practice_id == ctx.practice_id,
            FormTemplate.location_id == ctx.location_id,
            FormTemplate.archived_at.is_(None),
        )
        .group_by(FormTemplate.id)
        .order_by(func.count(FormRequest.id).desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def send_form(
    db: AsyncSession, ctx: StaffContext, data: SendFormRequest
) -> list[FormRequest]:
    patient = await db.get(Patient, data.patient_id)
    if patient is None or patient.practice_id != ctx.practice_id:
        raise ValueError("Patient not found")

    result = await db.execute(
        select(FormTemplate).where(
            FormTemplate.id.in_(data.form_template_ids),
            FormTemplate.practice_id == ctx.practice_id,
            FormTemplate.location_id == ctx.location_id,
        )
    )
    templates = result.scalars().all()
    if len(templates) != len(set(data.form_template_ids)):
        raise ValueError("Some forms could not be found")
    archived = [t.name for t in templates if t.archived_at is not None]
    if archived:
        raise ValueError(f"Cannot send an archived form: {', '.join(archived)}")

    now = _now()
    if data.expires_at is not None:
        expires_at = data.expires_at
    else:
        location = await db.get(Location, ctx.location_id)
        amount = location.form_expiration_amount if location else 7
        unit = location.form_expiration_unit if location else "days"
        expires_at = _compute_expires_at(amount, unit, now)
    if expires_at <= now:
        raise ValueError("Expiration date must be in the future")

    requests: list[FormRequest] = []
    for tpl in templates:
        req = FormRequest(
            practice_id=ctx.practice_id,
            location_id=ctx.location_id,
            patient_id=data.patient_id,
            form_template_id=tpl.id,
            expires_at=expires_at,
        )
        db.add(req)
        requests.append(req)
    await db.flush()

    raw_token = await create_form_access_token(
        db, practice_id=ctx.practice_id, location_id=ctx.location_id, patient_id=data.patient_id, expires_at=expires_at
    )
    link = f"{settings.frontend_url}/forms/{raw_token}"

    names = ", ".join(t.name for t in templates)
    text = data.message.strip() if data.message and data.message.strip() else f"Please fill out the following form(s): {names}"
    body = f"{text}\n{link}"
    await send_message(db, ctx, SendMessageRequest(patient_id=data.patient_id, body=body, channel="sms"))
    if data.email_note and data.email_note.strip():
        await send_message(
            db, ctx, SendMessageRequest(patient_id=data.patient_id, body=f"{data.email_note.strip()}\n{link}", channel="email")
        )

    await _log_activity(
        db,
        patient_id=data.patient_id,
        activity_type=ActivityType.FORM,
        title=f"Form{'s' if len(templates) != 1 else ''} sent — {names}",
    )
    return requests


async def evaluate_automatic_form_requests(
    db: AsyncSession, ctx: StaffContext, appointment: Appointment
) -> None:
    result = await db.execute(
        select(FormTemplate).where(
            FormTemplate.practice_id == ctx.practice_id,
            FormTemplate.location_id == ctx.location_id,
            FormTemplate.archived_at.is_(None),
            FormTemplate.send_automatically.is_(True),
        )
    )
    templates = result.scalars().all()
    if not templates:
        return

    patient = await db.get(Patient, appointment.patient_id)
    if patient is None:
        return

    prior_result = await db.execute(
        select(func.count()).select_from(Appointment).where(
            Appointment.patient_id == appointment.patient_id,
            Appointment.id != appointment.id,
            Appointment.status != AppointmentStatus.CANCELLED,
        )
    )
    patient_status = "existing" if prior_result.scalar_one() > 0 else "new"

    now = _now()
    age_years: int | None = None
    if patient.dob is not None:
        today = now.date()
        age_years = today.year - patient.dob.year - (
            (today.month, today.day) < (patient.dob.month, patient.dob.day)
        )

    type_result = await db.execute(
        select(AppointmentTypeDef.id).where(
            AppointmentTypeDef.practice_id == ctx.practice_id,
            AppointmentTypeDef.location_id == ctx.location_id,
            AppointmentTypeDef.name == appointment.appointment_type,
        )
    )
    matching_type_ids = {str(i) for i in type_result.scalars().all()}

    matched: list[FormTemplate] = []
    for tpl in templates:
        if tpl.rule_patient_status != "any" and tpl.rule_patient_status != patient_status:
            continue
        if tpl.rule_min_age is not None and (age_years is None or age_years < tpl.rule_min_age):
            continue
        if tpl.rule_max_age is not None and (age_years is None or age_years > tpl.rule_max_age):
            continue
        if tpl.rule_appointment_type_ids and not matching_type_ids & set(tpl.rule_appointment_type_ids):
            continue
        matched.append(tpl)
    if not matched:
        return

    filtered: list[FormTemplate] = []
    for tpl in matched:
        last_sent_result = await db.execute(
            select(func.max(FormRequest.sent_at)).where(
                FormRequest.patient_id == appointment.patient_id,
                FormRequest.form_template_id == tpl.id,
                FormRequest.archived_at.is_(None),
            )
        )
        last_sent = last_sent_result.scalar_one_or_none()
        if last_sent is not None:
            if tpl.rule_frequency_months:
                if last_sent + timedelta(days=30 * tpl.rule_frequency_months) > now:
                    continue
            elif last_sent.date() == now.date():
                continue
        filtered.append(tpl)
    if not filtered:
        return

    location = await db.get(Location, ctx.location_id)
    amount = location.form_expiration_amount if location else 7
    unit = location.form_expiration_unit if location else "days"
    expires_at = _compute_expires_at(amount, unit, now)

    for tpl in filtered:
        db.add(
            FormRequest(
                practice_id=ctx.practice_id,
                location_id=ctx.location_id,
                patient_id=appointment.patient_id,
                form_template_id=tpl.id,
                expires_at=expires_at,
            )
        )
    await db.flush()

    raw_token = await create_form_access_token(
        db, practice_id=ctx.practice_id, location_id=ctx.location_id, patient_id=appointment.patient_id, expires_at=expires_at
    )
    link = f"{settings.frontend_url}/forms/{raw_token}"

    names = ", ".join(t.name for t in filtered)
    body = f"Please fill out the following form(s): {names}\n{link}"
    await send_message(
        db, ctx, SendMessageRequest(patient_id=appointment.patient_id, body=body, channel="sms")
    )
    await _log_activity(
        db,
        patient_id=appointment.patient_id,
        activity_type=ActivityType.FORM,
        title=f"Form{'s' if len(filtered) != 1 else ''} sent automatically — {names}",
    )


async def list_form_request_batches(db: AsyncSession, ctx: StaffContext, *, tab: str) -> list[dict]:
    result = await db.execute(
        select(FormRequest, FormTemplate, Patient)
        .join(FormTemplate, FormTemplate.id == FormRequest.form_template_id)
        .join(Patient, Patient.id == FormRequest.patient_id)
        .where(
            FormRequest.practice_id == ctx.practice_id,
            FormRequest.location_id == ctx.location_id,
            FormRequest.archived_at.is_(None),
        )
        .order_by(FormRequest.sent_at.desc())
    )
    rows = result.all()

    now = _now()
    batches: dict[tuple, dict] = {}
    order: list[tuple] = []
    for req, tpl, patient in rows:
        key = (req.patient_id, req.sent_at)
        if key not in batches:
            batches[key] = {
                "patient_id": req.patient_id,
                "patient_name": f"{patient.first_name} {patient.last_name}".strip(),
                "patient_initials": f"{patient.first_name[:1]}{patient.last_name[:1]}".upper(),
                "request_ids": [],
                "sent_at": req.sent_at,
                "expires_at": req.expires_at,
                "forms": [],
                "statuses": [],
            }
            order.append(key)
        b = batches[key]
        b["request_ids"].append(req.id)
        b["forms"].append({"id": tpl.id, "name": tpl.name})
        b["statuses"].append(req.status)
        if req.expires_at > b["expires_at"]:
            b["expires_at"] = req.expires_at

    out: list[dict] = []
    for key in order:
        b = batches[key]
        statuses = b.pop("statuses")
        if all(s == FormRequestStatus.COMPLETED for s in statuses):
            status = "synced"
        elif now > b["expires_at"] + timedelta(hours=FORM_REQUEST_EXPIRY_GRACE_HOURS):
            status = "expired"
        else:
            status = "active"
        if tab != "all" and status != tab:
            continue
        b["status"] = status
        out.append(b)
    return out


async def reactivate_form_requests(
    db: AsyncSession, ctx: StaffContext, request_ids: list[uuid.UUID], expires_at: datetime
) -> None:
    now = _now()
    if expires_at <= now:
        raise ValueError("Due date must be in the future")
    result = await db.execute(
        select(FormRequest).where(
            FormRequest.id.in_(request_ids),
            FormRequest.practice_id == ctx.practice_id,
            FormRequest.location_id == ctx.location_id,
        )
    )
    requests = result.scalars().all()
    if len(requests) != len(set(request_ids)):
        raise ValueError("Some form requests could not be found")
    for req in requests:
        req.expires_at = expires_at
        req.status = FormRequestStatus.SENT
    await db.flush()


async def archive_form_requests(db: AsyncSession, ctx: StaffContext, request_ids: list[uuid.UUID]) -> None:
    result = await db.execute(
        select(FormRequest).where(
            FormRequest.id.in_(request_ids),
            FormRequest.practice_id == ctx.practice_id,
            FormRequest.location_id == ctx.location_id,
        )
    )
    requests = result.scalars().all()
    if len(requests) != len(set(request_ids)):
        raise ValueError("Some form requests could not be found")
    now = _now()
    for req in requests:
        req.archived_at = now
    await db.flush()


# ── Messages ─────────────────────────────────────────────────────────────────
async def list_messages(
    db: AsyncSession, ctx: StaffContext, *, patient_id: uuid.UUID | None = None
) -> list[tuple[Message, Patient]]:
    stmt = (
        select(Message, Patient)
        .join(MessageThread, MessageThread.id == Message.thread_id)
        .join(Patient, Patient.id == MessageThread.patient_id)
        .where(
            MessageThread.practice_id == ctx.practice_id,
            MessageThread.location_id == ctx.location_id,
        )
    )
    if patient_id:
        stmt = stmt.where(MessageThread.patient_id == patient_id)
    stmt = stmt.order_by(Message.sent_at.desc()).limit(100)
    result = await db.execute(stmt)
    return list(result.all())


async def send_message(
    db: AsyncSession, ctx: StaffContext, data: SendMessageRequest
) -> Message:
    result = await db.execute(
        select(MessageThread).where(
            MessageThread.patient_id == data.patient_id,
            MessageThread.practice_id == ctx.practice_id,
            MessageThread.location_id == ctx.location_id,
        )
    )
    thread = result.scalar_one_or_none()
    if thread is None:
        thread = MessageThread(
            practice_id=ctx.practice_id,
            location_id=ctx.location_id,
            patient_id=data.patient_id,
        )
        db.add(thread)
        await db.flush()
    msg = Message(
        thread_id=thread.id,
        direction="outbound",
        body=data.body,
        channel=MessageChannel(data.channel),
    )
    db.add(msg)
    await db.flush()
    await _log_activity(
        db,
        patient_id=data.patient_id,
        activity_type=ActivityType.MESSAGE,
        title="Message sent",
        body=data.body,
    )
    return msg


# ── Payments ─────────────────────────────────────────────────────────────────
async def list_payments(
    db: AsyncSession, ctx: StaffContext
) -> list[tuple[PaymentLink, Patient]]:
    result = await db.execute(
        select(PaymentLink, Patient)
        .join(Patient, Patient.id == PaymentLink.patient_id)
        .where(
            PaymentLink.practice_id == ctx.practice_id,
            PaymentLink.location_id == ctx.location_id,
        )
        .order_by(PaymentLink.created_at.desc())
    )
    return list(result.all())


async def create_payment_link(
    db: AsyncSession, ctx: StaffContext, data: PaymentLinkCreate
) -> PaymentLink:
    link = PaymentLink(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        patient_id=data.patient_id,
        amount=data.amount,
        description=data.description,
    )
    db.add(link)
    await db.flush()
    await _log_activity(
        db,
        patient_id=data.patient_id,
        activity_type=ActivityType.PAYMENT,
        title=f"Payment link created — ${data.amount}",
    )
    return link


# ── Insurance verification ───────────────────────────────────────────────────
async def verify_insurance(
    db: AsyncSession, ctx: StaffContext, patient_id: uuid.UUID
) -> Patient:
    patient = await get_patient(db, ctx, patient_id)
    if patient is None:
        raise ValueError("Patient not found")
    insurance = dict(patient.insurance_data or {})
    insurance.update(
        {
            "status": "active",
            "verifiedOn": _now().strftime("%m/%d/%Y"),
            "dataSource": "On Demand Verification",
        }
    )
    patient.insurance_data = insurance
    await _log_activity(
        db,
        patient_id=patient_id,
        activity_type=ActivityType.VERIFICATION,
        title="Insurance verified",
    )
    await db.flush()
    return patient


async def dashboard_stats(db: AsyncSession, ctx: StaffContext) -> dict:
    today = _now()
    appts = await list_appointments(db, ctx, day=today)
    confirmed = sum(1 for a, _ in appts if a.status == AppointmentStatus.CONFIRMED)
    waitlist = await list_waitlist(db, ctx)
    pending_forms = sum(1 for a, _ in appts if a.forms_status == FormsStatus.INCOMPLETE)
    payments = await list_payments(db, ctx)
    pending_payments = sum(1 for p, _ in payments if p.status == PaymentStatus.PENDING)
    return {
        "appointments_today": len(appts),
        "confirmed_count": confirmed,
        "waitlist_count": len(waitlist),
        "pending_forms": pending_forms,
        "pending_payments": pending_payments,
    }
