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
from app.models.practice import Practice
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
    MedicalAlert,
    Patient,
    PatientActivity,
    PaymentLink,
    PaymentStatus,
    PublicPacketSubmission,
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
    MedicalAlertCreate,
    MedicalAlertUpdate,
    PatientCreate,
    PatientUpdate,
    PaymentLinkCreate,
    SendFormRequest,
    SendMessageRequest,
    WaitlistCreate,
)
from app.services import appointment_rules_service, form_upload_storage

FORM_FIELD_TYPES = {
    "text", "textarea", "email", "number", "phone",
    "checkbox", "select_boxes", "dropdown", "radio",
    "date", "date_entry", "address", "file", "signature",
    "insurance", "preferred_language", "payment",
    "content", "location_logo", "columns", "panel",
    "medical_alerts_dropdown", "medical_alerts_radio",
}

MEDICAL_ALERT_CATEGORIES = ("condition", "allergy", "medication")

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
) -> tuple[str, uuid.UUID]:
    """Creates an opaque link token for the patient forms portal.

    Returns (raw_token, token_id). The raw value is never stored.
    """
    raw = security.generate_opaque_token()
    row = FormAccessToken(
        token_hash=security.hash_token(raw),
        practice_id=practice_id,
        location_id=location_id,
        patient_id=patient_id,
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    return raw, row.id


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


async def list_location_activity(
    db: AsyncSession,
    ctx: StaffContext,
    *,
    limit: int = 75,
) -> list[tuple[PatientActivity, Patient]]:
    """Recent patient activity at the active location."""
    result = await db.execute(
        select(PatientActivity, Patient)
        .join(Patient, Patient.id == PatientActivity.patient_id)
        .where(
            Patient.practice_id == ctx.practice_id,
            Patient.location_id == ctx.location_id,
        )
        .order_by(PatientActivity.created_at.desc())
        .limit(limit)
    )
    return list(result.all())


# ── Appointments ─────────────────────────────────────────────────────────────
async def list_appointments(
    db: AsyncSession,
    ctx: StaffContext,
    *,
    day: datetime | None = None,
    start_day: datetime | None = None,
    end_day: datetime | None = None,
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
    elif start_day is not None and end_day is not None:
        range_start = min(start_day.date(), end_day.date())
        range_end = max(start_day.date(), end_day.date())
        start = datetime.combine(range_start, time.min, tzinfo=timezone.utc)
        end = datetime.combine(range_end, time.max, tzinfo=timezone.utc)
        stmt = stmt.where(Appointment.starts_at >= start, Appointment.starts_at <= end)
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

    mapping_context = None
    if data.mapping_fields is not None:
        mapping_context = appointment_rules_service.MappingContext(
            provider_name=data.provider_name,
            operatory=data.mapping_fields.operatory,
            visit_type=data.mapping_fields.visit_type,
            service_type=data.mapping_fields.service_type,
            procedure_codes=data.mapping_fields.procedure_codes,
        )
    elif data.provider_name:
        mapping_context = appointment_rules_service.MappingContext(provider_name=data.provider_name)

    appt_type, meta = await appointment_rules_service.resolve_appointment_type(
        db,
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        appointment_type_id=data.appointment_type_id,
        appointment_type_name=data.appointment_type if not data.appointment_type_id else None,
        mapping_context=mapping_context,
        source="staff",
    )

    type_name = appt_type.name if appt_type else data.appointment_type
    duration = appt_type.duration_minutes if appt_type else data.duration_minutes

    appt = Appointment(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        patient_id=data.patient_id,
        provider_name=data.provider_name,
        appointment_type=type_name,
        appointment_type_def_id=appt_type.id if appt_type else None,
        starts_at=data.starts_at,
        duration_minutes=duration,
        status=AppointmentStatus(data.status),
        meta=meta,
    )
    db.add(appt)
    await db.flush()
    await _log_activity(
        db,
        patient_id=data.patient_id,
        activity_type=ActivityType.APPOINTMENT,
        title=f"Appointment scheduled — {type_name}",
        meta={"appointment_id": str(appt.id), **meta},
    )
    await evaluate_automatic_form_requests(
        db, practice_id=ctx.practice_id, location_id=ctx.location_id, appointment=appt, ctx=ctx
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
    prior_status = appt.status
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
    if (
        prior_status != AppointmentStatus.CONFIRMED
        and appt.status == AppointmentStatus.CONFIRMED
    ):
        await notify_automatic_forms_on_confirmation(db, ctx, appt)
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
    patient = await get_patient(db, ctx, data.patient_id)
    if patient is None:
        raise ValueError("Patient not found")
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
    await _log_activity(
        db,
        patient_id=data.patient_id,
        activity_type=ActivityType.NOTE,
        title="Added to waitlist",
        meta={"waitlist_entry_id": str(entry.id)},
    )
    return entry


async def remove_waitlist(db: AsyncSession, ctx: StaffContext, entry_id: uuid.UUID) -> WaitlistEntry | None:
    result = await db.execute(
        select(WaitlistEntry).where(
            WaitlistEntry.id == entry_id,
            WaitlistEntry.practice_id == ctx.practice_id,
            WaitlistEntry.location_id == ctx.location_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return None
    entry.status = WaitlistStatus.CANCELLED
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


# ── Medical alerts (Integrated Medical History forms) ───────────────────────
_STARTER_MEDICAL_ALERTS = {
    "condition": ["Anemia", "Artificial Joints", "Diabetes", "Head Injuries", "Heart Disease", "High Blood Pressure", "Jaundice", "Kidney Disease"],
    "allergy": ["Penicillin", "Latex", "Aspirin", "Sulfa Drugs", "Local Anesthetics"],
    "medication": ["Aspirin", "Ibuprofen", "Blood Thinners", "Insulin", "Antibiotics"],
}


async def _ensure_medical_alerts_seeded(db: AsyncSession, practice_id: uuid.UUID, location_id: uuid.UUID) -> None:
    result = await db.execute(
        select(func.count()).select_from(MedicalAlert).where(
            MedicalAlert.practice_id == practice_id,
            MedicalAlert.location_id == location_id,
        )
    )
    if result.scalar_one() > 0:
        return
    for category, labels in _STARTER_MEDICAL_ALERTS.items():
        for i, label in enumerate(labels):
            db.add(MedicalAlert(practice_id=practice_id, location_id=location_id, category=category, label=label, sort_order=i))
    await db.flush()
    # Catalog was previously seeded after the request had already committed, so
    # the IDs sent to the patient were rolled back and review could not resolve names.
    await db.commit()


async def list_medical_alerts(db: AsyncSession, ctx: StaffContext) -> list[MedicalAlert]:
    await _ensure_medical_alerts_seeded(db, ctx.practice_id, ctx.location_id)
    result = await db.execute(
        select(MedicalAlert)
        .where(MedicalAlert.practice_id == ctx.practice_id, MedicalAlert.location_id == ctx.location_id)
        .order_by(MedicalAlert.category, MedicalAlert.sort_order)
    )
    return list(result.scalars().all())


async def create_medical_alert(db: AsyncSession, ctx: StaffContext, data: MedicalAlertCreate) -> MedicalAlert:
    if data.category not in MEDICAL_ALERT_CATEGORIES:
        raise ValueError(f"Unknown category: {data.category}")
    if not data.label.strip():
        raise ValueError("Label is required")
    result = await db.execute(
        select(func.max(MedicalAlert.sort_order)).where(
            MedicalAlert.practice_id == ctx.practice_id,
            MedicalAlert.location_id == ctx.location_id,
            MedicalAlert.category == data.category,
        )
    )
    next_order = (result.scalar_one() or 0) + 1
    alert = MedicalAlert(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        category=data.category,
        label=data.label.strip(),
        flash=data.flash,
        sort_order=next_order,
        snomed_code=(data.snomed_code.strip() or None) if data.snomed_code is not None else None,
    )
    db.add(alert)
    await db.flush()
    return alert


async def update_medical_alert(
    db: AsyncSession, ctx: StaffContext, alert_id: uuid.UUID, data: MedicalAlertUpdate
) -> MedicalAlert:
    alert = await db.get(MedicalAlert, alert_id)
    if alert is None or alert.practice_id != ctx.practice_id or alert.location_id != ctx.location_id:
        raise ValueError("Medical alert not found")
    if data.label is not None:
        if not data.label.strip():
            raise ValueError("Label is required")
        alert.label = data.label.strip()
    if data.active is not None:
        alert.active = data.active
    if data.flash is not None:
        alert.flash = data.flash
    if data.snomed_code is not None:
        alert.snomed_code = data.snomed_code.strip() or None
    await db.flush()
    return alert


async def delete_medical_alert(db: AsyncSession, ctx: StaffContext, alert_id: uuid.UUID) -> None:
    alert = await db.get(MedicalAlert, alert_id)
    if alert is None or alert.practice_id != ctx.practice_id or alert.location_id != ctx.location_id:
        raise ValueError("Medical alert not found")
    await db.delete(alert)
    await db.flush()


async def move_medical_alert(db: AsyncSession, ctx: StaffContext, alert_id: uuid.UUID, direction: str) -> None:
    if direction not in ("up", "down"):
        raise ValueError("Direction must be 'up' or 'down'")
    alert = await db.get(MedicalAlert, alert_id)
    if alert is None or alert.practice_id != ctx.practice_id or alert.location_id != ctx.location_id:
        raise ValueError("Medical alert not found")

    result = await db.execute(
        select(MedicalAlert)
        .where(
            MedicalAlert.practice_id == ctx.practice_id,
            MedicalAlert.location_id == ctx.location_id,
            MedicalAlert.category == alert.category,
        )
        .order_by(MedicalAlert.sort_order)
    )
    siblings = result.scalars().all()
    idx = next(i for i, a in enumerate(siblings) if a.id == alert.id)
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if swap_idx < 0 or swap_idx >= len(siblings):
        return
    other = siblings[swap_idx]
    alert.sort_order, other.sort_order = other.sort_order, alert.sort_order
    await db.flush()


def _is_quoted_alert_label(label: str) -> bool:
    """Alerts phrased as a quoted question (e.g. "Are you allergic to peanuts?") are
    internal/PDF-only artifacts in some EHRs (Open Dental) — they never become a real
    patient-facing prompt, matching "NexHealth no longer creates long-form questions
    from alerts that have quotation marks around them."."""
    stripped = label.strip()
    return len(stripped) >= 2 and stripped.startswith('"') and stripped.endswith('"')


async def get_medical_alert_catalog(db: AsyncSession, practice_id: uuid.UUID, location_id: uuid.UUID) -> dict:
    await _ensure_medical_alerts_seeded(db, practice_id, location_id)
    result = await db.execute(
        select(MedicalAlert)
        .where(
            MedicalAlert.practice_id == practice_id,
            MedicalAlert.location_id == location_id,
            MedicalAlert.active.is_(True),
        )
        .order_by(MedicalAlert.category, MedicalAlert.sort_order)
    )
    catalog: dict[str, list[dict]] = {cat: [] for cat in MEDICAL_ALERT_CATEGORIES}
    for a in result.scalars().all():
        if _is_quoted_alert_label(a.label):
            continue
        catalog.setdefault(a.category, []).append({"id": str(a.id), "label": a.label})
    return catalog


def form_has_medical_alerts(template: FormTemplate) -> bool:
    return any(f.get("type") in ("medical_alerts_dropdown", "medical_alerts_radio") for f in template.fields)


def _form_field(
    fid: str,
    ftype: str,
    label: str,
    *,
    required: bool = True,
    options: list[str] | None = None,
    sync_target: str | None = None,
    placeholder: str = "",
    page: int = 1,
    conditional_field_id: str | None = None,
    conditional_value: str = "",
) -> dict:
    return {
        "id": fid,
        "type": ftype,
        "label": label,
        "required": required,
        "options": options or [],
        "page": page,
        "min_length": None,
        "max_length": None,
        "conditional_field_id": conditional_field_id,
        "conditional_value": conditional_value,
        "sync_target": sync_target,
        "placeholder": placeholder,
    }


_STARTER_FORMS: list[dict] = [
    {
        "name": "Medical History",
        "form_type": "Medical",
        "is_default": True,
        "fields": [
            _form_field("medical-alerts", "medical_alerts_dropdown", "Medical History", sync_target="patient.medical_alerts"),
        ],
    },
    {
        "name": "Patient Information",
        "form_type": "Profile",
        "is_default": False,
        "fields": [
            _form_field("first-name", "text", "First name", sync_target="patient.first_name", placeholder="Jane"),
            _form_field("last-name", "text", "Last name", sync_target="patient.last_name", placeholder="Doe"),
            _form_field("dob", "date", "Date of birth", sync_target="patient.date_of_birth"),
            _form_field("email", "email", "Email", sync_target="patient.email", placeholder="jane@email.com"),
            _form_field("phone", "phone", "Phone number", sync_target="patient.phone", placeholder="(415) 555-0100"),
            _form_field("address", "address", "Home address", sync_target="patient.address", placeholder="123 Main St, Brooklyn, NY 11225"),
        ],
    },
    {
        "name": "Visit Preferences",
        "form_type": "Intake",
        "is_default": False,
        "fields": [
            _form_field("married", "radio", "Are you married?", options=["Yes", "No"], sync_target="patient.marital_status"),
            _form_field(
                "visit-reason",
                "dropdown",
                "Reason for today's visit",
                options=["Cleaning", "Tooth pain", "Check-up", "Follow-up", "Other"],
                sync_target="appointment.visit_reason",
            ),
            _form_field(
                "reminders",
                "select_boxes",
                "How should we remind you?",
                required=False,
                options=["Text", "Email", "Phone call"],
                sync_target="patient.reminders",
            ),
            _form_field("language", "preferred_language", "Preferred language", sync_target="patient.preferred_language"),
            _form_field("notes", "textarea", "Anything else we should know?", required=False, placeholder="Optional", sync_target="appointment.notes"),
        ],
    },
    {
        "name": "Insurance & Payment",
        "form_type": "Financial",
        "is_default": False,
        "fields": [
            _form_field("has-insurance", "radio", "Do you have dental insurance?", options=["Yes", "No"]),
            _form_field(
                "insurance",
                "insurance",
                "Insurance provider",
                required=False,
                sync_target="patient.insurance",
                conditional_field_id="has-insurance",
                conditional_value="Yes",
            ),
            _form_field("card-front", "file", "Insurance card photo", required=False),
            _form_field("payment", "payment", "How will you pay today?", required=False, sync_target="patient.payment_preference"),
        ],
    },
    {
        "name": "Consent & Signature",
        "form_type": "Consent",
        "is_default": False,
        "fields": [
            _form_field(
                "hipaa-consent",
                "checkbox",
                "I agree to the HIPAA privacy practices and to receive treatment today.",
                sync_target="patient.hipaa_consent",
            ),
            _form_field("consent-notes", "textarea", "Questions or comments for the office", required=False, sync_target="appointment.notes"),
            _form_field("signature", "signature", "Type your full name to sign", sync_target="patient.signature"),
            _form_field("signed-on", "date", "Today's date", sync_target="patient.signed_on"),
        ],
    },
]


async def _ensure_named_form_template(
    db: AsyncSession,
    practice_id: uuid.UUID,
    location_id: uuid.UUID,
    spec: dict,
) -> None:
    result = await db.execute(
        select(FormTemplate).where(
            FormTemplate.practice_id == practice_id,
            FormTemplate.location_id == location_id,
            FormTemplate.name == spec["name"],
        )
    )
    tpl = result.scalar_one_or_none()
    desired = {f.get("id"): f for f in spec["fields"]}
    if tpl is not None:
        fields = list(tpl.fields or [])
        changed = False
        next_fields: list[dict] = []
        for field in fields:
            src = desired.get(field.get("id"))
            if not src:
                next_fields.append(field)
                continue

            next_field = dict(field)
            if src.get("sync_target") and field.get("sync_target") != src.get("sync_target"):
                next_field["sync_target"] = src["sync_target"]
                changed = True

            # Keep starter conditional logic in sync for known fields.
            src_cond_id = src.get("conditional_field_id")
            src_cond_val = src.get("conditional_value", "")
            if field.get("conditional_field_id") != src_cond_id:
                next_field["conditional_field_id"] = src_cond_id
                changed = True
            if field.get("conditional_value", "") != src_cond_val:
                next_field["conditional_value"] = src_cond_val
                changed = True

            next_fields.append(next_field)
        if changed:
            tpl.fields = next_fields
        return
    existing_default = await db.execute(
        select(func.count()).select_from(FormTemplate).where(
            FormTemplate.practice_id == practice_id,
            FormTemplate.location_id == location_id,
            FormTemplate.is_default.is_(True),
        )
    )
    make_default = bool(spec.get("is_default")) and existing_default.scalar_one() == 0
    db.add(
        FormTemplate(
            practice_id=practice_id,
            location_id=location_id,
            name=spec["name"],
            form_type=spec.get("form_type") or "",
            source="build",
            status="active",
            display_type="wizard",
            fields=spec["fields"],
            page_count=1,
            is_default=make_default,
        )
    )


async def seed_starter_form_templates(db: AsyncSession, practice_id: uuid.UUID, location_id: uuid.UUID) -> None:
    """Idempotent starter templates so local/dev locations can test chat + standard intake."""
    await _ensure_medical_alerts_seeded(db, practice_id, location_id)
    for spec in _STARTER_FORMS:
        await _ensure_named_form_template(db, practice_id, location_id, spec)
    await db.flush()


async def seed_default_medical_history_form(
    db: AsyncSession, practice_id: uuid.UUID, location_id: uuid.UUID
) -> None:
    """New locations get a Medical History form out of the box — "the Medical History
    form is automatically generated when the Synchronizer is installed" (matches this
    app's equivalent moment: when a new location is created)."""
    await seed_starter_form_templates(db, practice_id, location_id)


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
        rule_procedure_codes=[c.strip() for c in data.rule_procedure_codes if c.strip()],
    )
    db.add(tpl)
    await db.flush()
    return tpl


async def has_form_submissions(db: AsyncSession, template_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(func.count())
        .select_from(FormSubmission)
        .join(FormRequest, FormRequest.id == FormSubmission.form_request_id)
        .where(FormRequest.form_template_id == template_id)
    )
    return result.scalar_one() > 0


async def is_form_template_locked(db: AsyncSession, template: FormTemplate) -> bool:
    """Medical History forms become immutable once a real patient has submitted one —
    mirrors Eaglesoft's own "can't edit a filled-out Medical Form" rule."""
    if not form_has_medical_alerts(template):
        return False
    return await has_form_submissions(db, template.id)


async def update_form_template(
    db: AsyncSession, template: FormTemplate, data: FormTemplateUpdate
) -> FormTemplate:
    if await is_form_template_locked(db, template):
        raise ValueError(
            "This Medical History form has real patient submissions and can't be edited — duplicate it to make changes."
        )
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
    template.rule_procedure_codes = [c.strip() for c in data.rule_procedure_codes if c.strip()]
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
        send_automatically=template.send_automatically,
        rule_patient_status=template.rule_patient_status,
        rule_frequency_months=template.rule_frequency_months,
        rule_min_age=template.rule_min_age,
        rule_max_age=template.rule_max_age,
        rule_appointment_type_ids=template.rule_appointment_type_ids,
        rule_procedure_codes=template.rule_procedure_codes,
    )
    db.add(copy)
    await db.flush()
    return copy


async def set_default_form_template(db: AsyncSession, ctx: StaffContext, template: FormTemplate) -> None:
    if not form_has_medical_alerts(template):
        raise ValueError("Only Medical History forms can be marked as default")
    result = await db.execute(
        select(FormTemplate).where(
            FormTemplate.practice_id == ctx.practice_id,
            FormTemplate.location_id == ctx.location_id,
            FormTemplate.is_default.is_(True),
        )
    )
    for other in result.scalars().all():
        other.is_default = False
    template.is_default = True
    await db.flush()


async def copy_form_templates(
    db: AsyncSession,
    ctx: StaffContext,
    template_ids: list[uuid.UUID],
    packet_ids: list[uuid.UUID],
    location_ids: list[uuid.UUID],
) -> dict[str, int]:
    if not template_ids and not packet_ids:
        raise ValueError("Select at least one form or packet to copy")

    packets: list[FormPacket] = []
    if packet_ids:
        pkt_result = await db.execute(
            select(FormPacket).where(
                FormPacket.id.in_(packet_ids),
                FormPacket.practice_id == ctx.practice_id,
                FormPacket.location_id == ctx.location_id,
            )
        )
        packets = list(pkt_result.scalars().all())
        if len(packets) != len(set(packet_ids)):
            raise ValueError("Some packets could not be found in your current location")

    all_template_ids = set(template_ids)
    for pkt in packets:
        all_template_ids.update(uuid.UUID(str(tid)) for tid in pkt.form_template_ids)

    sources: list[FormTemplate] = []
    if all_template_ids:
        result = await db.execute(
            select(FormTemplate).where(
                FormTemplate.id.in_(all_template_ids),
                FormTemplate.practice_id == ctx.practice_id,
                FormTemplate.location_id == ctx.location_id,
            )
        )
        sources = list(result.scalars().all())
        if len(sources) != len(all_template_ids):
            raise ValueError("Some forms could not be found in your current location")

    target_locations = [lid for lid in dict.fromkeys(location_ids) if lid != ctx.location_id]
    if not target_locations:
        raise ValueError("Select at least one other location to copy to")

    forms_copied = 0
    packets_copied = 0
    for loc_id in target_locations:
        id_map: dict[uuid.UUID, uuid.UUID] = {}
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
                existing.send_automatically = src.send_automatically
                existing.rule_patient_status = src.rule_patient_status
                existing.rule_frequency_months = src.rule_frequency_months
                existing.rule_min_age = src.rule_min_age
                existing.rule_max_age = src.rule_max_age
                existing.rule_appointment_type_ids = src.rule_appointment_type_ids
                existing.rule_procedure_codes = src.rule_procedure_codes
                id_map[src.id] = existing.id
            else:
                new_tpl = FormTemplate(
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
                    send_automatically=src.send_automatically,
                    rule_patient_status=src.rule_patient_status,
                    rule_frequency_months=src.rule_frequency_months,
                    rule_min_age=src.rule_min_age,
                    rule_max_age=src.rule_max_age,
                    rule_appointment_type_ids=src.rule_appointment_type_ids,
                    rule_procedure_codes=src.rule_procedure_codes,
                )
                db.add(new_tpl)
                await db.flush()
                id_map[src.id] = new_tpl.id
            forms_copied += 1

        for pkt in packets:
            remapped = [str(id_map[uuid.UUID(str(tid))]) for tid in pkt.form_template_ids]
            existing_pkt_result = await db.execute(
                select(FormPacket).where(
                    FormPacket.practice_id == ctx.practice_id,
                    FormPacket.location_id == loc_id,
                    FormPacket.name == pkt.name,
                )
            )
            existing_pkt = existing_pkt_result.scalar_one_or_none()
            if existing_pkt:
                existing_pkt.form_template_ids = remapped
            else:
                db.add(
                    FormPacket(
                        practice_id=ctx.practice_id,
                        location_id=loc_id,
                        name=pkt.name,
                        form_template_ids=remapped,
                    )
                )
            packets_copied += 1

    await db.flush()
    return {"copied": forms_copied + packets_copied, "forms_copied": forms_copied, "packets_copied": packets_copied}


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


async def duplicate_form_packet(db: AsyncSession, ctx: StaffContext, packet: FormPacket) -> FormPacket:
    copy = FormPacket(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        name=f"{packet.name} (copy)",
        form_template_ids=list(packet.form_template_ids),
    )
    db.add(copy)
    await db.flush()
    return copy


async def delete_form_packet(db: AsyncSession, packet: FormPacket) -> None:
    await db.delete(packet)
    await db.flush()


async def enable_packet_public_access(db: AsyncSession, packet: FormPacket) -> FormPacket:
    """Idempotent: returns the packet's existing public code, generating one on first use."""
    if packet.public_code:
        return packet
    for _ in range(5):
        candidate = security.generate_opaque_token()[:11]
        existing = await db.execute(select(FormPacket.id).where(FormPacket.public_code == candidate))
        if existing.scalar_one_or_none() is None:
            packet.public_code = candidate
            break
    await db.flush()
    return packet


async def list_public_packet_submissions(db: AsyncSession, ctx: StaffContext) -> list[dict]:
    result = await db.execute(
        select(PublicPacketSubmission, FormPacket)
        .join(FormPacket, FormPacket.id == PublicPacketSubmission.form_packet_id)
        .where(
            PublicPacketSubmission.practice_id == ctx.practice_id,
            PublicPacketSubmission.location_id == ctx.location_id,
            PublicPacketSubmission.assigned_patient_id.is_(None),
        )
        .order_by(PublicPacketSubmission.created_at.desc())
    )
    out: list[dict] = []
    for sub, packet in result.all():
        out.append(
            {
                "id": sub.id,
                "form_packet_id": sub.form_packet_id,
                "packet_name": packet.name,
                "first_name": sub.first_name,
                "last_name": sub.last_name,
                "dob": sub.dob,
                "phone": sub.phone,
                "email": sub.email,
                "form_names": [s.get("form_name", "") for s in sub.submissions],
                "created_at": sub.created_at,
            }
        )
    return out


async def assign_public_packet_submission(
    db: AsyncSession, ctx: StaffContext, submission_id: uuid.UUID, patient_id: uuid.UUID
) -> None:
    sub = await db.get(PublicPacketSubmission, submission_id)
    if sub is None or sub.practice_id != ctx.practice_id or sub.location_id != ctx.location_id:
        raise ValueError("Submission not found")
    if sub.assigned_patient_id is not None:
        raise ValueError("This submission has already been assigned")

    patient = await db.get(Patient, patient_id)
    if patient is None or patient.practice_id != ctx.practice_id or patient.location_id != ctx.location_id:
        raise ValueError("Patient not found")

    names: list[str] = []
    request_ids: list[uuid.UUID] = []
    for entry in sub.submissions:
        template_id = entry.get("template_id")
        form_name = entry.get("form_name", "")
        answers = entry.get("answers", {})
        req = FormRequest(
            practice_id=ctx.practice_id,
            location_id=ctx.location_id,
            patient_id=patient.id,
            form_template_id=uuid.UUID(template_id),
            status=FormRequestStatus.COMPLETED,
            sent_at=sub.created_at,
            expires_at=sub.created_at,
            sync_status="pending",
        )
        db.add(req)
        await db.flush()
        db.add(
            FormSubmission(
                form_request_id=req.id,
                patient_id=patient.id,
                form_name=form_name,
                device="web",
                sync_status="complete",
                answers=answers,
                submitted_at=sub.created_at,
            )
        )
        names.append(form_name)
        request_ids.append(req.id)

    sub.assigned_patient_id = patient.id
    await db.flush()

    from app.services.form_ehr_sync_service import apply_form_sync_outcome

    all_synced = True
    for req_id in request_ids:
        req = await db.get(FormRequest, req_id)
        if req is None:
            continue
        status = await apply_form_sync_outcome(db, req, patient, force=True)
        if status != "synced":
            all_synced = False

    if all_synced:
        sub.synced_at = _now()

    await _log_activity(
        db,
        patient_id=patient.id,
        activity_type=ActivityType.FORM,
        title=f"Form{'s' if len(names) != 1 else ''} assigned from public packet — {', '.join(names)}",
    )
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


async def _deliver_form_intake_notifications(
    db: AsyncSession,
    ctx: StaffContext,
    patient: Patient,
    *,
    form_names: str,
    raw_token: str,
    intake_mode: str | None = None,
    custom_sms: str | None = None,
    custom_email: str | None = None,
) -> dict[str, str]:
    """Log SMS + send real email (SES) with form/agent intake link(s)."""
    from app.services import email_service
    from app.services.form_intake_links import build_intake_links, format_intake_sms_body

    mode = (intake_mode or settings.agent_default_intake_mode or "agent").strip()
    links = build_intake_links(raw_token, mode)
    assistant = settings.ai_assistant_name or "Angelina"

    sms_body = format_intake_sms_body(
        form_names=form_names,
        links=links,
        custom_message=custom_sms,
        assistant_name=assistant,
    )
    await send_message(
        db, ctx, SendMessageRequest(patient_id=patient.id, body=sms_body, channel="sms")
    )

    email = (patient.email or "").strip()
    if email:
        practice = await db.get(Practice, ctx.practice_id)
        practice_name = practice.name if practice else "Your clinic"
        patient_name = patient.preferred_name or patient.first_name or "there"
        try:
            email_service.send_form_intake(
                to=email,
                patient_name=patient_name,
                practice_name=practice_name,
                form_names=form_names,
                primary_link=links["primary_link"],
                secondary_link=links.get("secondary_link") or "",
                intake_mode=links["mode"],
                assistant_name=assistant,
                custom_note=custom_email,
            )
            email_log = f"{custom_email.strip()}\n{links['primary_link']}" if custom_email and custom_email.strip() else sms_body
            await send_message(
                db,
                ctx,
                SendMessageRequest(patient_id=patient.id, body=email_log, channel="email"),
            )
        except email_service.EmailDeliveryError:
            # Still logged SMS; email failure should not roll back form request.
            pass

    return links


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

    from app.services.form_completion_service import get_upcoming_appointment

    linked_appt = await get_upcoming_appointment(
        db, patient_id=data.patient_id, location_id=ctx.location_id
    )

    requests: list[FormRequest] = []
    for tpl in templates:
        req = FormRequest(
            practice_id=ctx.practice_id,
            location_id=ctx.location_id,
            patient_id=data.patient_id,
            form_template_id=tpl.id,
            expires_at=expires_at,
            appointment_id=linked_appt.id if linked_appt else None,
        )
        db.add(req)
        requests.append(req)
    await db.flush()

    raw_token, token_id = await create_form_access_token(
        db, practice_id=ctx.practice_id, location_id=ctx.location_id, patient_id=data.patient_id, expires_at=expires_at
    )
    for req in requests:
        req.form_access_token_id = token_id
    await db.flush()
    names = ", ".join(t.name for t in templates)
    custom_sms = data.message.strip() if data.message and data.message.strip() else None
    custom_email = data.email_note.strip() if data.email_note and data.email_note.strip() else None
    links = await _deliver_form_intake_notifications(
        db,
        ctx,
        patient,
        form_names=names,
        raw_token=raw_token,
        intake_mode=data.intake_mode,
        custom_sms=custom_sms,
        custom_email=custom_email,
    )

    await _log_activity(
        db,
        patient_id=data.patient_id,
        activity_type=ActivityType.FORM,
        title=f"Form{'s' if len(templates) != 1 else ''} sent — {names}",
        body=links["primary_link"],
    )
    return requests


def _norm_procedure_code(code: str) -> str:
    return str(code).strip().upper()


async def _patient_is_new(db: AsyncSession, patient_id: uuid.UUID, exclude_appointment_id: uuid.UUID) -> bool:
    """New patients have never had a completed (checked-in) appointment."""
    prior_result = await db.execute(
        select(func.count()).select_from(Appointment).where(
            Appointment.patient_id == patient_id,
            Appointment.id != exclude_appointment_id,
            Appointment.status == AppointmentStatus.CHECKED_IN,
        )
    )
    return prior_result.scalar_one() == 0


async def _should_skip_form_frequency(
    db: AsyncSession, *, patient_id: uuid.UUID, template: FormTemplate, now: datetime
) -> bool:
    if template.rule_frequency_months:
        last_completed_result = await db.execute(
            select(func.max(FormSubmission.submitted_at))
            .join(FormRequest, FormRequest.id == FormSubmission.form_request_id)
            .where(
                FormRequest.patient_id == patient_id,
                FormRequest.form_template_id == template.id,
                FormRequest.status == FormRequestStatus.COMPLETED,
            )
        )
        last_completed = last_completed_result.scalar_one_or_none()
        if last_completed is not None:
            return last_completed + timedelta(days=30 * template.rule_frequency_months) > now
        return False

    ever_sent_result = await db.execute(
        select(func.count()).select_from(FormRequest).where(
            FormRequest.patient_id == patient_id,
            FormRequest.form_template_id == template.id,
        )
    )
    return ever_sent_result.scalar_one() > 0


async def notify_automatic_forms_on_confirmation(
    db: AsyncSession, ctx: StaffContext, appointment: Appointment
) -> None:
    """Send form links after a patient confirms their appointment (SMS reminder sequence)."""
    appt_date = appointment.starts_at.date()
    result = await db.execute(
        select(FormRequest, FormTemplate)
        .join(FormTemplate, FormTemplate.id == FormRequest.form_template_id)
        .where(
            FormRequest.patient_id == appointment.patient_id,
            FormRequest.practice_id == ctx.practice_id,
            FormRequest.location_id == ctx.location_id,
            FormRequest.archived_at.is_(None),
            FormRequest.status != FormRequestStatus.COMPLETED,
            func.date(FormRequest.expires_at) == appt_date,
        )
    )
    rows = result.all()
    if not rows:
        return

    templates = [tpl for _, tpl in rows]
    expires_at = rows[0][0].expires_at
    raw_token, token_id = await create_form_access_token(
        db,
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        patient_id=appointment.patient_id,
        expires_at=expires_at,
    )
    for req, _tpl in rows:
        req.form_access_token_id = token_id
    await db.flush()
    names = ", ".join(t.name for t in templates)
    patient = await db.get(Patient, appointment.patient_id)
    if patient:
        await _deliver_form_intake_notifications(
            db, ctx, patient, form_names=names, raw_token=raw_token, intake_mode=settings.agent_default_intake_mode
        )
    await _log_activity(
        db,
        patient_id=appointment.patient_id,
        activity_type=ActivityType.FORM,
        title=f"Form{'s' if len(templates) != 1 else ''} sent automatically — {names}",
    )


async def evaluate_automatic_form_requests(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID,
    location_id: uuid.UUID,
    appointment: Appointment,
    ctx: StaffContext | None = None,
) -> None:
    result = await db.execute(
        select(FormTemplate).where(
            FormTemplate.practice_id == practice_id,
            FormTemplate.location_id == location_id,
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

    appt_date = appointment.starts_at.date()
    dup_result = await db.execute(
        select(func.count()).select_from(FormRequest).where(
            FormRequest.patient_id == appointment.patient_id,
            FormRequest.practice_id == practice_id,
            FormRequest.location_id == location_id,
            func.date(FormRequest.expires_at) == appt_date,
        )
    )
    if dup_result.scalar_one() > 0:
        return

    patient_is_new = await _patient_is_new(db, appointment.patient_id, appointment.id)
    patient_status = "new" if patient_is_new else "existing"

    now = _now()
    age_years: int | None = None
    if patient.dob is not None:
        today = now.date()
        age_years = today.year - patient.dob.year - (
            (today.month, today.day) < (patient.dob.month, patient.dob.day)
        )

    if appointment.appointment_type_def_id is not None:
        matching_type_ids = {str(appointment.appointment_type_def_id)}
    else:
        type_result = await db.execute(
            select(AppointmentTypeDef.id).where(
                AppointmentTypeDef.practice_id == practice_id,
                AppointmentTypeDef.location_id == location_id,
                AppointmentTypeDef.name == appointment.appointment_type,
            )
        )
        matching_type_ids = {str(i) for i in type_result.scalars().all()}

    meta = appointment.meta or {}
    appt_procedure_codes = {_norm_procedure_code(c) for c in meta.get("procedure_codes", []) if str(c).strip()}

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
        if tpl.rule_procedure_codes:
            rule_codes = {_norm_procedure_code(c) for c in tpl.rule_procedure_codes if str(c).strip()}
            if not appt_procedure_codes & rule_codes:
                continue
        matched.append(tpl)
    if not matched:
        return

    filtered: list[FormTemplate] = []
    for tpl in matched:
        if await _should_skip_form_frequency(db, patient_id=appointment.patient_id, template=tpl, now=now):
            continue
        filtered.append(tpl)
    if not filtered:
        return

    expires_at = appointment.starts_at

    new_requests: list[FormRequest] = []
    for tpl in filtered:
        req = FormRequest(
            practice_id=practice_id,
            location_id=location_id,
            patient_id=appointment.patient_id,
            form_template_id=tpl.id,
            expires_at=expires_at,
            appointment_id=appointment.id,
        )
        db.add(req)
        new_requests.append(req)
    await db.flush()

    if ctx is None:
        return
    if appointment.status not in (AppointmentStatus.CONFIRMED, AppointmentStatus.CHECKED_IN):
        return

    raw_token, token_id = await create_form_access_token(
        db, practice_id=practice_id, location_id=location_id, patient_id=appointment.patient_id, expires_at=expires_at
    )
    for req in new_requests:
        req.form_access_token_id = token_id
    await db.flush()
    names = ", ".join(t.name for t in filtered)
    patient = await db.get(Patient, appointment.patient_id)
    if patient and ctx is not None:
        await _deliver_form_intake_notifications(
            db, ctx, patient, form_names=names, raw_token=raw_token, intake_mode=settings.agent_default_intake_mode
        )
    await _log_activity(
        db,
        patient_id=appointment.patient_id,
        activity_type=ActivityType.FORM,
        title=f"Form{'s' if len(filtered) != 1 else ''} sent automatically — {names}",
    )


async def list_form_request_batches(db: AsyncSession, ctx: StaffContext, *, tab: str) -> list[dict]:
    archived_only = tab == "deleted"
    result = await db.execute(
        select(FormRequest, FormTemplate, Patient)
        .join(FormTemplate, FormTemplate.id == FormRequest.form_template_id)
        .join(Patient, Patient.id == FormRequest.patient_id)
        .where(
            FormRequest.practice_id == ctx.practice_id,
            FormRequest.location_id == ctx.location_id,
            FormRequest.archived_at.isnot(None) if archived_only else FormRequest.archived_at.is_(None),
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
                "viewed_flags": [],
                "sync_statuses": [],
            }
            order.append(key)
        b = batches[key]
        b["request_ids"].append(req.id)
        b["forms"].append({"id": tpl.id, "name": tpl.name})
        b["statuses"].append(req.status)
        b["viewed_flags"].append(req.viewed_at is not None)
        b["sync_statuses"].append(req.sync_status)
        if req.expires_at > b["expires_at"]:
            b["expires_at"] = req.expires_at

    out: list[dict] = []
    for key in order:
        b = batches[key]
        statuses = b.pop("statuses")
        viewed_flags = b.pop("viewed_flags")
        sync_statuses = b.pop("sync_statuses")

        completed_count = sum(1 for s in statuses if s == FormRequestStatus.COMPLETED)
        all_completed = completed_count == len(statuses)
        all_synced = all_completed and all(s == "synced" for s in sync_statuses)

        if all_synced:
            status = "synced"
        elif not all_completed and now > b["expires_at"] + timedelta(hours=FORM_REQUEST_EXPIRY_GRACE_HOURS):
            status = "expired"
        else:
            status = "active"
        if not archived_only and tab != "all" and status != tab:
            continue

        if all_completed:
            completed_status = "complete"
        elif completed_count > 0:
            completed_status = "in_progress"
        elif any(viewed_flags):
            completed_status = "viewed"
        else:
            completed_status = "sent"

        sync_status: str | None = None
        if all_completed and not all_synced:
            sync_status = "sync-failed" if any(s == "failed" for s in sync_statuses) else "sync-now"

        b["status"] = status
        b["completed_status"] = completed_status
        b["sync_status"] = sync_status
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


async def delete_form_requests(db: AsyncSession, ctx: StaffContext, request_ids: list[uuid.UUID]) -> None:
    """Permanently remove form requests (and cascaded submissions / agent sessions)."""
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
        await db.delete(req)
    await db.flush()


async def sync_form_requests(db: AsyncSession, ctx: StaffContext, request_ids: list[uuid.UUID]) -> None:
    from app.services.form_ehr_sync_service import apply_form_sync_outcome

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
        if req.status != FormRequestStatus.COMPLETED:
            continue
        patient = await db.get(Patient, req.patient_id)
        if patient is None:
            req.sync_status = "failed"
            continue
        await apply_form_sync_outcome(db, req, patient, force=True)
    await db.flush()


async def mark_synced_form_requests(db: AsyncSession, ctx: StaffContext, request_ids: list[uuid.UUID]) -> None:
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
        req.sync_status = "synced"
        req.synced_at = now
        await _log_activity(
            db,
            patient_id=req.patient_id,
            activity_type=ActivityType.FORM,
            title="Form marked as synced outside NexHealth",
            meta={"form_request_id": str(req.id), "manual_mark": True},
        )
    await db.flush()


async def get_form_request_submissions(
    db: AsyncSession, ctx: StaffContext, request_ids: list[uuid.UUID]
) -> list[FormSubmission]:
    result = await db.execute(
        select(FormSubmission)
        .join(FormRequest, FormRequest.id == FormSubmission.form_request_id)
        .where(
            FormSubmission.form_request_id.in_(request_ids),
            FormRequest.practice_id == ctx.practice_id,
            FormRequest.location_id == ctx.location_id,
        )
    )
    return list(result.scalars().all())


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


async def dashboard_stats(
    db: AsyncSession,
    ctx: StaffContext,
    *,
    start_day: datetime | None = None,
    end_day: datetime | None = None,
) -> dict:
    if start_day is not None and end_day is not None:
        appts = await list_appointments(db, ctx, start_day=start_day, end_day=end_day)
    else:
        appts = await list_appointments(db, ctx)

    confirmed = sum(1 for a, _ in appts if a.status == AppointmentStatus.CONFIRMED)
    unconfirmed = sum(1 for a, _ in appts if a.status == AppointmentStatus.UNCONFIRMED)
    waitlist = await list_waitlist(db, ctx)
    pending_forms = sum(1 for a, _ in appts if a.forms_status == FormsStatus.INCOMPLETE)
    payments = await list_payments(db, ctx)
    pending_payments = sum(1 for p, _ in payments if p.status == PaymentStatus.PENDING)
    return {
        "appointments_today": len(appts),
        "confirmed_count": confirmed,
        "unconfirmed_count": unconfirmed,
        "waitlist_count": len(waitlist),
        "pending_forms": pending_forms,
        "pending_payments": pending_payments,
    }
