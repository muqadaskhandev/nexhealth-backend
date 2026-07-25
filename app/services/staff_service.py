"""Staff workflow business logic."""
from __future__ import annotations

import uuid
from datetime import datetime, time, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_context import StaffContext
from app.models.staff import (
    ActivityType,
    Appointment,
    AppointmentStatus,
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
    template.name = data.name.strip()
    template.form_type = data.form_type
    template.display_type = data.display_type
    template.fields = [f.model_dump() for f in data.fields]
    template.page_count = data.page_count
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


async def send_form(
    db: AsyncSession, ctx: StaffContext, data: SendFormRequest
) -> FormRequest:
    tpl = await db.get(FormTemplate, data.form_template_id)
    if tpl is None or tpl.practice_id != ctx.practice_id or tpl.location_id != ctx.location_id:
        raise ValueError("Form template not found")
    req = FormRequest(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        patient_id=data.patient_id,
        form_template_id=data.form_template_id,
    )
    db.add(req)
    await db.flush()
    await _log_activity(
        db,
        patient_id=data.patient_id,
        activity_type=ActivityType.FORM,
        title=f"Form sent — {tpl.name}",
    )
    return req


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
