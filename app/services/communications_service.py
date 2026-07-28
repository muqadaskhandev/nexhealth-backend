"""Communication templates service — list, activate, edit steps, sending hours."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.staff_context import StaffContext
from app.models.appointment_types import AppointmentTypeDef
from app.models.communications import (
    DEFAULT_OOO_MESSAGE,
    DEFAULT_SERVICE_HOURS,
    CommunicationTemplate,
    CommunicationTemplateStep,
    OutOfOfficeSettings,
    SavedResponse,
    SmsRegistration,
    SmsRegistrationStatus,
    TemplateAutomationSend,
    TemplateCategory,
    TemplateConfiguration,
    TemplateStepKind,
)
from app.models.location import Location
from app.models.staff import Appointment, Patient
from app.schemas.communications import (
    CommunicationTemplateUpdate,
    OutOfOfficeSettingsUpdate,
    SavedResponseCreate,
    SavedResponseUpdate,
    SmsRegistrationStatusUpdate,
    SmsRegistrationUpdate,
    TemplateAppointmentTypeStatus,
    TemplateConfigurationUpdate,
    TemplateStepCreate,
    TemplateStepUpdate,
    TemplateVariantToggle,
)

# Template slugs that support per-appointment-type customization (Appointment Journeys + related).
CUSTOMIZABLE_SLUGS = frozenset(
    {
        "reminders",
        "post-appointment-follow-up",
        "recalls",
        "appointment-request",
        "appointment-confirmed",
        "save-the-date",
        "appointment-rescheduled",
    }
)
# Default automations offered by NexHealth (seeded per location on first access).
_DEFAULT_TEMPLATES: list[dict] = [
    {
        "slug": "appointment-request",
        "name": "NexHealth Appointment Request",
        "description": "Sent when a patient books an appointment online using NexHealth.",
        "category": TemplateCategory.APPOINTMENT_JOURNEY,
        "is_active": True,
        "total_sent": 28,
        "recipients": 27,
        "steps": [
            {"kind": TemplateStepKind.TRIGGER, "title": "Appointment booked online", "subtitle": "When patient books", "position": 0},
            {"kind": TemplateStepKind.EMAIL, "title": "Appointment Request Email", "subject": "Your appointment request", "body": "Hi {{PATIENT_FIRST_NAME}}, we received your appointment request at {{LOCATION_NAME}}.", "position": 1},
            {"kind": TemplateStepKind.SMS, "title": "Appointment Request SMS", "body": "Hi {{PATIENT_FIRST_NAME}}, we received your appointment request. Reply HELP for help.", "position": 2},
        ],
    },
    {
        "slug": "appointment-confirmed",
        "name": "NexHealth Appointment Confirmed",
        "description": "Sent when you confirm the appointment that the patient requested online.",
        "category": TemplateCategory.APPOINTMENT_JOURNEY,
        "is_active": True,
        "total_sent": 4,
        "recipients": 4,
        "steps": [
            {"kind": TemplateStepKind.TRIGGER, "title": "Appointment confirmed", "subtitle": "When staff confirms", "position": 0},
            {"kind": TemplateStepKind.EMAIL, "title": "Confirmed Email", "subject": "Your appointment is confirmed", "body": "Your appointment with {{LOCATION_NAME}} is confirmed for {{APPOINTMENT_DATE}}.", "position": 1},
            {"kind": TemplateStepKind.SMS, "title": "Confirmed SMS", "body": "Your appointment is confirmed for {{APPOINTMENT_DATE}} at {{APPOINTMENT_TIME}}.", "position": 2},
        ],
    },
    {
        "slug": "save-the-date",
        "name": "Save the Date",
        "description": (
            "Sent when a new appointment is scheduled on your practice management calendar "
            "(e.g. phone or front desk). Only sends once to the same phone number and patient "
            "name within a 6-hour window; eligible messages are not merged into one."
        ),
        "category": TemplateCategory.APPOINTMENT_JOURNEY,
        "is_active": True,
        "total_sent": 68,
        "recipients": 41,
        "steps": [
            {"kind": TemplateStepKind.TRIGGER, "title": "Appointment scheduled", "subtitle": "On PMS calendar", "position": 0},
            {"kind": TemplateStepKind.EMAIL, "title": "Save the Date Email", "subject": "Save the date", "body": "We look forward to seeing you soon! Your appointment with {{LOCATION_NAME}} is {{APPOINTMENT_DATE}}.", "position": 1},
            {"kind": TemplateStepKind.SMS, "title": "Save the Date SMS", "body": "Save the date: {{APPOINTMENT_DATE}} at {{APPOINTMENT_TIME}} with {{LOCATION_NAME}}.", "position": 2},
        ],
    },
    {
        "slug": "appointment-rescheduled",
        "name": "NexHealth Appointment Rescheduled",
        "description": "Sent immediately when you move an appointment to a different time on the NexHealth calendar. Only for customers not syncing with an EHR who use the NexHealth calendar.",
        "category": TemplateCategory.APPOINTMENT_JOURNEY,
        "is_active": False,
        "total_sent": 1,
        "recipients": 1,
        "steps": [
            {"kind": TemplateStepKind.TRIGGER, "title": "Appointment rescheduled", "subtitle": "On NexHealth calendar", "position": 0},
            {"kind": TemplateStepKind.EMAIL, "title": "Rescheduled Email", "subject": "Your appointment was rescheduled", "body": "Your appointment has been moved to {{APPOINTMENT_DATE}} at {{APPOINTMENT_TIME}}.", "position": 1},
            {"kind": TemplateStepKind.SMS, "title": "Rescheduled SMS", "body": "Your appointment was rescheduled to {{APPOINTMENT_DATE}} at {{APPOINTMENT_TIME}}.", "position": 2},
        ],
    },
    {
        "slug": "reminders",
        "name": "Reminders",
        "description": "Sent at set time intervals before an appointment (default: one week and one day before). Timing is adjustable via the gray time tiles in the editor.",
        "category": TemplateCategory.APPOINTMENT_JOURNEY,
        "is_active": True,
        "multi_location": True,
        "total_sent": 63,
        "recipients": 37,
        "steps": [
            {
                "kind": TemplateStepKind.TRIGGER,
                "title": "Next action",
                "subtitle": "1 week Reminders",
                "timing_value": 1,
                "timing_unit": "week",
                "condition_label": "Send if unconfirmed",
                "position": 0,
            },
            {
                "kind": TemplateStepKind.EMAIL,
                "title": "Reminders Email",
                "subject": "Your appointment with {{LOCATION_NAME}} is {{APPOINTMENT_TIME}}",
                "body": "We look forward to seeing you soon!\n\nYour appointment with {{LOCATION_NAME}} is coming up soon, {{PATIENT_FIRST_NAME}}. Here are all the details:",
                "position": 1,
            },
            {
                "kind": TemplateStepKind.SMS,
                "title": "Reminders SMS",
                "body": (
                    "Hi {{PATIENT_FIRST_NAME}}, reminder: your appointment at {{LOCATION_NAME}} "
                    "is on {{APPOINTMENT_DATE}} at {{APPOINTMENT_TIME}}.\n\n"
                    "{{APPOINTMENT_DETAILS}}\n\n"
                    "Reply C to confirm: {{INSERTCONFIRMAPPT}}\n"
                    "{{APPOINTMENT_REGISTRATION}}"
                ),
                "position": 2,
            },
        ],
    },
    {
        "slug": "missed",
        "name": "Missed",
        "description": "At 7:45pm, for every patient whose appointment was not canceled, checked in, or rescheduled (no-show). Only sends if the patient does not have an upcoming appointment in the next 6 months.",
        "category": TemplateCategory.DAILY,
        "is_active": True,
        "total_sent": 7,
        "recipients": 6,
        "steps": [
            {"kind": TemplateStepKind.TRIGGER, "title": "Missed appointment", "subtitle": "Daily at 7:45 PM", "position": 0},
            {"kind": TemplateStepKind.EMAIL, "title": "Missed Email", "subject": "We missed you", "body": "Hi {{PATIENT_FIRST_NAME}}, we missed you today. Reply to reschedule.", "position": 1},
            {"kind": TemplateStepKind.SMS, "title": "Missed SMS", "body": "Hi {{PATIENT_FIRST_NAME}}, we missed you at your appointment today. Call us to reschedule.", "position": 2},
        ],
    },
    {
        "slug": "cancelled",
        "name": "Cancelled",
        "description": "At 7:45pm, for patients who cancelled an appointment and have not rescheduled. Sent on the day the canceled appointment was originally scheduled unless they have another appointment in the next 6 months.",
        "category": TemplateCategory.DAILY,
        "is_active": False,
        "total_sent": 3,
        "recipients": 3,
        "steps": [
            {"kind": TemplateStepKind.TRIGGER, "title": "Cancelled appointment", "subtitle": "Daily at 7:45 PM", "position": 0},
            {"kind": TemplateStepKind.EMAIL, "title": "Cancelled Email", "subject": "Sorry we couldn't see you", "body": "Hi {{PATIENT_FIRST_NAME}}, your appointment was cancelled. Book again anytime.", "position": 1},
            {"kind": TemplateStepKind.SMS, "title": "Cancelled SMS", "body": "Hi {{PATIENT_FIRST_NAME}}, your appointment was cancelled. Reply to book a new time.", "position": 2},
        ],
    },
    {
        "slug": "reviews",
        "name": "Reviews",
        "description": "At 7:30pm, for every patient who had an appointment on the calendar and kept their appointment (did not cancel, reschedule, or no-show).",
        "category": TemplateCategory.DAILY,
        "is_active": True,
        "total_sent": 36,
        "recipients": 26,
        "steps": [
            {"kind": TemplateStepKind.TRIGGER, "title": "Appointment completed", "subtitle": "Daily at 7:30 PM", "position": 0},
            {"kind": TemplateStepKind.EMAIL, "title": "Reviews Email", "subject": "How was your visit?", "body": "Hi {{PATIENT_FIRST_NAME}}, thanks for visiting {{LOCATION_NAME}}. We'd love your feedback!", "position": 1},
            {"kind": TemplateStepKind.SMS, "title": "Reviews SMS", "body": "Thanks for visiting {{LOCATION_NAME}}! Leave a review: {{REVIEW_LINK}}", "position": 2},
        ],
    },
    {
        "slug": "post-appointment-follow-up",
        "name": "Post Appointment Follow-up",
        "description": "Goes out after an appointment to check in or provide further instructions. Frequency and time of day are customizable through the grey time tiles.",
        "category": TemplateCategory.POST_APPOINTMENT,
        "is_active": True,
        "total_sent": 157,
        "recipients": 99,
        "steps": [
            {"kind": TemplateStepKind.TRIGGER, "title": "After appointment", "subtitle": "1 day after", "timing_value": 1, "timing_unit": "day", "position": 0},
            {"kind": TemplateStepKind.EMAIL, "title": "Follow-up Email", "subject": "How are you feeling?", "body": "Hi {{PATIENT_FIRST_NAME}}, thanks for coming in. Here are your post-visit instructions.", "position": 1},
            {"kind": TemplateStepKind.SMS, "title": "Follow-up SMS", "body": "Hi {{PATIENT_FIRST_NAME}}, hope you're feeling well after your visit. Call us with questions.", "position": 2},
        ],
    },
    {
        "slug": "recalls",
        "name": "Recalls",
        "description": "Triggered by the date of the patient's last appointment; by default sent 6 months after if they have not made another. Frequency and time of day are customizable.",
        "category": TemplateCategory.POST_APPOINTMENT,
        "is_active": True,
        "total_sent": 42,
        "recipients": 38,
        "steps": [
            {"kind": TemplateStepKind.TRIGGER, "title": "Recall due", "subtitle": "6 months after last visit", "timing_value": 6, "timing_unit": "month", "position": 0},
            {"kind": TemplateStepKind.EMAIL, "title": "Recalls Email", "subject": "Time for your next visit", "body": "Hi {{PATIENT_FIRST_NAME}}, it's time to schedule your next appointment at {{LOCATION_NAME}}.", "position": 1},
            {"kind": TemplateStepKind.SMS, "title": "Recalls SMS", "body": "Hi {{PATIENT_FIRST_NAME}}, time for your recall visit. Book at {{LOCATION_NAME}}.", "position": 2},
        ],
    },
    {
        "slug": "new-patient",
        "name": "New Patient",
        "description": (
            "Sent when a new patient is added to your health record system. NexHealth checks "
            "every 15 minutes between 8 AM and 7 PM. Sends on patient create, not on booking. "
            "Like other non-reminder templates, only once per phone + patient name within 6 hours."
        ),
        "category": TemplateCategory.PATIENT_BASED,
        "is_active": False,
        "total_sent": 12,
        "recipients": 12,
        "steps": [
            {"kind": TemplateStepKind.TRIGGER, "title": "New patient added", "subtitle": "Every 15 min, 8 AM–7 PM", "position": 0},
            {"kind": TemplateStepKind.EMAIL, "title": "New Patient Email", "subject": "Welcome to {{LOCATION_NAME}}", "body": "Welcome {{PATIENT_FIRST_NAME}}! We're glad you're here.", "position": 1},
            {"kind": TemplateStepKind.SMS, "title": "New Patient SMS", "body": "Welcome to {{LOCATION_NAME}}, {{PATIENT_FIRST_NAME}}!", "position": 2},
        ],
    },
    {
        "slug": "birthday",
        "name": "Birthday",
        "description": "The birthday message is sent at 12:45 PM on the patient's birthday.",
        "category": TemplateCategory.PATIENT_BASED,
        "is_active": True,
        "total_sent": 18,
        "recipients": 18,
        "steps": [
            {"kind": TemplateStepKind.TRIGGER, "title": "Patient birthday", "subtitle": "12:45 PM", "position": 0},
            {"kind": TemplateStepKind.EMAIL, "title": "Birthday Email", "subject": "Happy birthday!", "body": "Happy birthday, {{PATIENT_FIRST_NAME}}! From all of us at {{LOCATION_NAME}}.", "position": 1},
            {"kind": TemplateStepKind.SMS, "title": "Birthday SMS", "body": "Happy birthday {{PATIENT_FIRST_NAME}}! — {{LOCATION_NAME}}", "position": 2},
        ],
    },
    {
        "slug": "payments",
        "name": "Payments",
        "description": "Triggered when a NexHealth payment request is manually sent by staff. Does not automatically read due balances.",
        "category": TemplateCategory.MANUAL,
        "is_active": True,
        "total_sent": 112,
        "recipients": 89,
        "steps": [
            {"kind": TemplateStepKind.TRIGGER, "title": "Next action", "subtitle": "Payments", "position": 0},
            {"kind": TemplateStepKind.EMAIL, "title": "Payments Email", "subject": "Payment request", "body": "Hi {{PATIENT_FIRST_NAME}}, you have a payment request from {{LOCATION_NAME}}.", "position": 1},
            {"kind": TemplateStepKind.SMS, "title": "Payments SMS", "body": "Hi {{PATIENT_FIRST_NAME}}, {{LOCATION_NAME}} sent you a payment request.", "position": 2},
        ],
    },
    {
        "slug": "waitlist-appointment",
        "name": "Waitlist Appointment",
        "description": "Sends to patients on the ASAP, Missed or Cancelled list when a Waitlist blast is created via Your waitlist or Missed or cancelled.",
        "category": TemplateCategory.MANUAL,
        "is_active": True,
        "total_sent": 24,
        "recipients": 24,
        "steps": [
            {"kind": TemplateStepKind.TRIGGER, "title": "Waitlist blast", "subtitle": "Your waitlist / Missed or cancelled", "position": 0},
            {"kind": TemplateStepKind.EMAIL, "title": "Waitlist Email", "subject": "An earlier appointment is available", "body": "Hi {{PATIENT_FIRST_NAME}}, an earlier appointment opened up!", "position": 1},
            {"kind": TemplateStepKind.SMS, "title": "Waitlist SMS", "body": "Hi {{PATIENT_FIRST_NAME}}, an earlier slot is available at {{LOCATION_NAME}}. Claim it now!", "position": 2},
        ],
    },
    {
        "slug": "waitlist-continuing-care",
        "name": "Waitlist Continuing Care",
        "description": "Sends to patients on the ASAP, Missed or Cancelled list when a Waitlist blast is created via the Continuing care button.",
        "category": TemplateCategory.MANUAL,
        "is_active": True,
        "total_sent": 9,
        "recipients": 9,
        "steps": [
            {"kind": TemplateStepKind.TRIGGER, "title": "Continuing care blast", "subtitle": "Continuing care button", "position": 0},
            {"kind": TemplateStepKind.EMAIL, "title": "Continuing Care Email", "subject": "Continuing care opening", "body": "Hi {{PATIENT_FIRST_NAME}}, a continuing care appointment is available.", "position": 1},
            {"kind": TemplateStepKind.SMS, "title": "Continuing Care SMS", "body": "Hi {{PATIENT_FIRST_NAME}}, a continuing care slot opened at {{LOCATION_NAME}}.", "position": 2},
        ],
    },
    {
        "slug": "form-request",
        "name": "Form Request",
        "description": "Triggered when a form is manually sent to a patient. Includes automatic form reminders one day and one hour before the form due date.",
        "category": TemplateCategory.MANUAL,
        "is_active": True,
        "total_sent": 55,
        "recipients": 48,
        "steps": [
            {"kind": TemplateStepKind.TRIGGER, "title": "Form sent", "subtitle": "Manual form request", "position": 0},
            {"kind": TemplateStepKind.EMAIL, "title": "Form Request Email", "subject": "Please complete your forms", "body": "Hi {{PATIENT_FIRST_NAME}}, please complete your forms before your visit: {{FORM_LINK}}", "position": 1},
            {"kind": TemplateStepKind.SMS, "title": "Form Request SMS", "body": "Hi {{PATIENT_FIRST_NAME}}, please complete your forms: {{FORM_LINK}}", "position": 2},
        ],
    },
    {
        "slug": "form-reminder",
        "name": "Form Reminder",
        "description": "Triggered when office staff use Send reminder in the Forms tab for an outstanding form request.",
        "category": TemplateCategory.MANUAL,
        "is_active": True,
        "total_sent": 21,
        "recipients": 19,
        "steps": [
            {"kind": TemplateStepKind.TRIGGER, "title": "Form reminder", "subtitle": "Send reminder", "position": 0},
            {"kind": TemplateStepKind.EMAIL, "title": "Form Reminder Email", "subject": "Reminder: complete your forms", "body": "Hi {{PATIENT_FIRST_NAME}}, this is a reminder to complete your forms: {{FORM_LINK}}", "position": 1},
            {"kind": TemplateStepKind.SMS, "title": "Form Reminder SMS", "body": "Reminder from {{LOCATION_NAME}}: please complete your forms {{FORM_LINK}}", "position": 2},
        ],
    },
]


async def _ensure_templates_seeded(db: AsyncSession, ctx: StaffContext) -> None:
    existing = await db.scalar(
        select(CommunicationTemplate.id).where(
            CommunicationTemplate.location_id == ctx.location_id
        ).limit(1)
    )
    if existing:
        return

    for spec in _DEFAULT_TEMPLATES:
        steps_spec = spec["steps"]
        tmpl = CommunicationTemplate(
            practice_id=ctx.practice_id,
            location_id=ctx.location_id,
            slug=spec["slug"],
            name=spec["name"],
            description=spec["description"],
            category=spec["category"],
            is_active=spec.get("is_active", False),
            total_sent=spec.get("total_sent", 0),
            recipients=spec.get("recipients", 0),
            multi_location=bool(spec.get("multi_location", False)),
        )
        db.add(tmpl)
        await db.flush()
        for step in steps_spec:
            db.add(
                CommunicationTemplateStep(
                    template_id=tmpl.id,
                    kind=step["kind"],
                    title=step["title"],
                    subtitle=step.get("subtitle", ""),
                    body=step.get("body", ""),
                    subject=step.get("subject", ""),
                    timing_value=step.get("timing_value"),
                    timing_unit=step.get("timing_unit"),
                    condition_label=step.get("condition_label"),
                    position=step["position"],
                )
            )

    await db.commit()


async def list_templates(
    db: AsyncSession,
    ctx: StaffContext,
    *,
    scope: str = "default",
) -> list[CommunicationTemplate]:
    """scope: default | variants | all"""
    await _ensure_templates_seeded(db, ctx)
    loc = await db.get(Location, ctx.location_id)
    location_name = loc.name if loc else ""

    stmt = (
        select(CommunicationTemplate)
        .where(CommunicationTemplate.location_id == ctx.location_id)
        .options(selectinload(CommunicationTemplate.steps))
        .order_by(CommunicationTemplate.name)
    )
    if scope == "default":
        stmt = stmt.where(CommunicationTemplate.appointment_type_id.is_(None))
    elif scope == "variants":
        stmt = stmt.where(CommunicationTemplate.appointment_type_id.is_not(None))

    rows = list(await db.scalars(stmt))

    # Attach appointment type names for variants
    type_ids = {r.appointment_type_id for r in rows if r.appointment_type_id}
    type_names: dict[uuid.UUID, str] = {}
    if type_ids:
        for t in await db.scalars(
            select(AppointmentTypeDef).where(AppointmentTypeDef.id.in_(type_ids))
        ):
            type_names[t.id] = t.name

    for row in rows:
        row.location_name = location_name  # type: ignore[attr-defined]
        row.appointment_type_name = (  # type: ignore[attr-defined]
            type_names.get(row.appointment_type_id, "") if row.appointment_type_id else ""
        )
    return rows


async def get_template(db: AsyncSession, ctx: StaffContext, template_id: uuid.UUID) -> CommunicationTemplate:
    await _ensure_templates_seeded(db, ctx)
    tmpl = await db.scalar(
        select(CommunicationTemplate)
        .where(
            CommunicationTemplate.id == template_id,
            CommunicationTemplate.location_id == ctx.location_id,
        )
        .options(selectinload(CommunicationTemplate.steps))
    )
    if not tmpl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    loc = await db.get(Location, ctx.location_id)
    tmpl.location_name = loc.name if loc else ""  # type: ignore[attr-defined]
    if tmpl.appointment_type_id:
        at = await db.get(AppointmentTypeDef, tmpl.appointment_type_id)
        tmpl.appointment_type_name = at.name if at else ""  # type: ignore[attr-defined]
    else:
        tmpl.appointment_type_name = ""  # type: ignore[attr-defined]
    return tmpl


async def get_template_by_slug(
    db: AsyncSession,
    ctx: StaffContext,
    slug: str,
    *,
    appointment_type_id: uuid.UUID | None = None,
) -> CommunicationTemplate:
    await _ensure_templates_seeded(db, ctx)
    stmt = (
        select(CommunicationTemplate)
        .where(
            CommunicationTemplate.slug == slug,
            CommunicationTemplate.location_id == ctx.location_id,
        )
        .options(selectinload(CommunicationTemplate.steps))
    )
    if appointment_type_id is None:
        stmt = stmt.where(CommunicationTemplate.appointment_type_id.is_(None))
    else:
        stmt = stmt.where(CommunicationTemplate.appointment_type_id == appointment_type_id)
    tmpl = await db.scalar(stmt)
    if not tmpl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    loc = await db.get(Location, ctx.location_id)
    tmpl.location_name = loc.name if loc else ""  # type: ignore[attr-defined]
    if tmpl.appointment_type_id:
        at = await db.get(AppointmentTypeDef, tmpl.appointment_type_id)
        tmpl.appointment_type_name = at.name if at else ""  # type: ignore[attr-defined]
    else:
        tmpl.appointment_type_name = ""  # type: ignore[attr-defined]
    return tmpl


async def list_appointment_type_status(
    db: AsyncSession, ctx: StaffContext, slug: str
) -> list[TemplateAppointmentTypeStatus]:
    """Which appointment types have a custom sequence enabled for this template slug."""
    await _ensure_templates_seeded(db, ctx)
    if slug not in CUSTOMIZABLE_SLUGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This template type does not support per-appointment-type customization",
        )

    types = list(
        await db.scalars(
            select(AppointmentTypeDef)
            .where(
                AppointmentTypeDef.practice_id == ctx.practice_id,
                AppointmentTypeDef.location_id == ctx.location_id,
            )
            .order_by(AppointmentTypeDef.position, AppointmentTypeDef.name)
        )
    )
    variants = list(
        await db.scalars(
            select(CommunicationTemplate).where(
                CommunicationTemplate.location_id == ctx.location_id,
                CommunicationTemplate.slug == slug,
                CommunicationTemplate.appointment_type_id.is_not(None),
            )
        )
    )
    by_type = {v.appointment_type_id: v for v in variants}

    return [
        TemplateAppointmentTypeStatus(
            appointment_type_id=t.id,
            appointment_type_name=t.name,
            enabled=bool(by_type.get(t.id) and by_type[t.id].is_active),
            variant_id=by_type[t.id].id if by_type.get(t.id) else None,
        )
        for t in types
    ]


async def set_variant_for_appointment_type(
    db: AsyncSession,
    ctx: StaffContext,
    slug: str,
    data: TemplateVariantToggle,
) -> CommunicationTemplate | None:
    """Enable: clone default template for appointment type. Disable: deactivate (keep for history)."""
    await _ensure_templates_seeded(db, ctx)
    if slug not in CUSTOMIZABLE_SLUGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This template type does not support per-appointment-type customization",
        )

    at = await db.get(AppointmentTypeDef, data.appointment_type_id)
    if not at or at.location_id != ctx.location_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment type not found")

    existing = await db.scalar(
        select(CommunicationTemplate)
        .where(
            CommunicationTemplate.location_id == ctx.location_id,
            CommunicationTemplate.slug == slug,
            CommunicationTemplate.appointment_type_id == data.appointment_type_id,
        )
        .options(selectinload(CommunicationTemplate.steps))
    )

    if not data.enabled:
        if existing:
            existing.is_active = False
            await db.commit()
        return existing

    if existing:
        existing.is_active = True
        await db.commit()
        return await get_template(db, ctx, existing.id)

    base = await get_template_by_slug(db, ctx, slug)
    variant = CommunicationTemplate(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        slug=base.slug,
        name=f"{base.name} — {at.name}",
        description=base.description,
        category=base.category,
        is_active=True,
        total_sent=0,
        recipients=0,
        multi_location=False,
        appointment_type_id=at.id,
    )
    db.add(variant)
    await db.flush()
    for step in base.steps:
        db.add(
            CommunicationTemplateStep(
                template_id=variant.id,
                kind=step.kind,
                title=step.title,
                subtitle=step.subtitle,
                body=step.body,
                subject=step.subject,
                timing_value=step.timing_value,
                timing_unit=step.timing_unit,
                condition_label=step.condition_label,
                position=step.position,
                meta=dict(step.meta or {}),
            )
        )
    await db.commit()
    return await get_template(db, ctx, variant.id)


async def update_template(
    db: AsyncSession,
    ctx: StaffContext,
    template_id: uuid.UUID,
    data: CommunicationTemplateUpdate,
) -> CommunicationTemplate:
    tmpl = await get_template(db, ctx, template_id)
    if data.is_active is not None:
        tmpl.is_active = data.is_active
    if data.description is not None:
        tmpl.description = data.description
    await db.commit()
    return await get_template(db, ctx, template_id)


async def update_step(
    db: AsyncSession,
    ctx: StaffContext,
    template_id: uuid.UUID,
    step_id: uuid.UUID,
    data: TemplateStepUpdate,
) -> CommunicationTemplateStep:
    tmpl = await get_template(db, ctx, template_id)
    step = next((s for s in tmpl.steps if s.id == step_id), None)
    if not step:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Step not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(step, field, value)
    await db.commit()
    await db.refresh(step)
    return step


async def add_step(
    db: AsyncSession,
    ctx: StaffContext,
    template_id: uuid.UUID,
    data: TemplateStepCreate,
) -> CommunicationTemplateStep:
    tmpl = await get_template(db, ctx, template_id)
    next_pos = max((s.position for s in tmpl.steps), default=-1) + 1
    kind = TemplateStepKind.EMAIL if data.kind == "email" else TemplateStepKind.SMS
    step = CommunicationTemplateStep(
        template_id=tmpl.id,
        kind=kind,
        title=data.title,
        body=data.body,
        subject=data.subject,
        position=next_pos,
    )
    db.add(step)
    await db.commit()
    await db.refresh(step)
    return step


async def delete_step(
    db: AsyncSession,
    ctx: StaffContext,
    template_id: uuid.UUID,
    step_id: uuid.UUID,
) -> None:
    tmpl = await get_template(db, ctx, template_id)
    step = next((s for s in tmpl.steps if s.id == step_id), None)
    if not step:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Step not found")
    if step.kind == TemplateStepKind.TRIGGER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete trigger step")
    await db.delete(step)
    await db.commit()


async def get_or_create_config(db: AsyncSession, ctx: StaffContext) -> TemplateConfiguration:
    config = await db.scalar(
        select(TemplateConfiguration).where(TemplateConfiguration.location_id == ctx.location_id)
    )
    if config:
        return config
    config = TemplateConfiguration(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        sending_hours_start=time(6, 0),
        sending_hours_end=time(22, 0),
        customize_by_appointment_type=False,
        family_messaging_enabled=False,
        use_family_messaging_for_reminders=False,
        family_messaging_age_limit=None,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config


async def update_config(
    db: AsyncSession,
    ctx: StaffContext,
    data: TemplateConfigurationUpdate,
) -> TemplateConfiguration:
    config = await get_or_create_config(db, ctx)
    payload = data.model_dump(exclude_unset=True)
    start = payload.get("sending_hours_start", config.sending_hours_start)
    end = payload.get("sending_hours_end", config.sending_hours_end)
    if start is not None and end is not None and end <= start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End time must be after start time",
        )
    if "sending_hours_start" in payload and payload["sending_hours_start"] is not None:
        config.sending_hours_start = payload["sending_hours_start"]
    if "sending_hours_end" in payload and payload["sending_hours_end"] is not None:
        config.sending_hours_end = payload["sending_hours_end"]
    if "customize_by_appointment_type" in payload and payload["customize_by_appointment_type"] is not None:
        config.customize_by_appointment_type = payload["customize_by_appointment_type"]
    if "family_messaging_enabled" in payload and payload["family_messaging_enabled"] is not None:
        config.family_messaging_enabled = payload["family_messaging_enabled"]
        # Turning off family messaging also turns off reminders consolidation
        if not payload["family_messaging_enabled"]:
            config.use_family_messaging_for_reminders = False
    if (
        "use_family_messaging_for_reminders" in payload
        and payload["use_family_messaging_for_reminders"] is not None
    ):
        if payload["use_family_messaging_for_reminders"] and not config.family_messaging_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Enable family messaging before using it for Reminders",
            )
        config.use_family_messaging_for_reminders = payload["use_family_messaging_for_reminders"]
    if "family_messaging_age_limit" in payload:
        config.family_messaging_age_limit = payload["family_messaging_age_limit"]
    await db.commit()
    await db.refresh(config)
    return config


_HISTORY_FALLBACK_NAMES = [
    ("Albert Einstein", date(1879, 3, 14)),
    ("Marie Curie", date(1867, 11, 7)),
    ("Isaac Newton", date(1643, 1, 4)),
    ("Nikola Tesla", date(1856, 7, 10)),
    ("Louis Pasteur", date(1822, 12, 27)),
    ("Alexander Fleming", date(1881, 8, 6)),
]

_HISTORY_LABELS_BY_SLUG: dict[str, list[str]] = {
    "reminders": ["1 day reminder", "1 day reminder", "2 day reminder", "1 week reminder"],
    "recalls": ["Recall reminder", "6 month recall"],
    "reviews": ["Review request"],
        "payments": ["Payment request"],
    "form-reminder": ["Form reminder"],
    "save-the-date": ["Save the Date"],
    "new-patient": ["New patient welcome"],
}


def _default_history_labels(slug: str) -> list[str]:
    return _HISTORY_LABELS_BY_SLUG.get(slug) or [f"{slug.replace('-', ' ').title()} send"]


async def _ensure_template_history_seeded(
    db: AsyncSession, ctx: StaffContext, template: CommunicationTemplate
) -> None:
    """Seed demo automation history so History tab has recipients to browse."""
    count = await db.scalar(
        select(func.count())
        .select_from(TemplateAutomationSend)
        .where(TemplateAutomationSend.template_id == template.id)
    )
    if count and count > 0:
        return

    patients = list(
        await db.scalars(
            select(Patient)
            .where(
                Patient.practice_id == ctx.practice_id,
                Patient.location_id == ctx.location_id,
            )
            .order_by(Patient.last_name.asc())
            .limit(8)
        )
    )

    appts = list(
        await db.scalars(
            select(Appointment)
            .where(
                Appointment.practice_id == ctx.practice_id,
                Appointment.location_id == ctx.location_id,
            )
            .order_by(Appointment.starts_at.desc())
            .limit(12)
        )
    )
    appt_by_patient = {a.patient_id: a for a in appts}

    now = datetime.now(timezone.utc)
    labels = _default_history_labels(template.slug)
    rows: list[TemplateAutomationSend] = []

    if patients:
        for i, patient in enumerate(patients[:6]):
            appt = appt_by_patient.get(patient.id)
            label = labels[i % len(labels)]
            channel = "sms" if i % 2 == 0 else "email"
            rows.append(
                TemplateAutomationSend(
                    practice_id=ctx.practice_id,
                    location_id=ctx.location_id,
                    template_id=template.id,
                    patient_id=patient.id,
                    patient_name=f"{patient.first_name} {patient.last_name}".strip(),
                    patient_dob=patient.dob,
                    communication_label=label,
                    channel=channel,
                    sent_at=now - timedelta(days=i, hours=3 - (i % 3), minutes=15),
                    provider_name=(appt.provider_name if appt else "Hygienist - Hyg"),
                    appointment_at=appt.starts_at if appt else now + timedelta(days=1, hours=10 + i),
                )
            )
    else:
        for i, (name, dob) in enumerate(_HISTORY_FALLBACK_NAMES):
            label = labels[i % len(labels)]
            channel = "sms" if i % 2 == 0 else "email"
            rows.append(
                TemplateAutomationSend(
                    practice_id=ctx.practice_id,
                    location_id=ctx.location_id,
                    template_id=template.id,
                    patient_id=None,
                    patient_name=name,
                    patient_dob=dob,
                    communication_label=label,
                    channel=channel,
                    sent_at=now - timedelta(days=i, hours=3, minutes=15),
                    provider_name="Hygienist - Hyg",
                    appointment_at=now + timedelta(days=1, hours=10 + i * 0.5),
                )
            )

    for row in rows:
        db.add(row)
    # Keep list/performance counts in sync with seeded history
    template.total_sent = max(template.total_sent, len(rows))
    template.recipients = max(template.recipients, len({r.patient_name for r in rows}))
    await db.commit()


async def list_template_history(
    db: AsyncSession,
    ctx: StaffContext,
    template_id: uuid.UUID,
    *,
    q: str | None = None,
    sent_from: date | None = None,
    sent_to: date | None = None,
) -> list[TemplateAutomationSend]:
    template = await get_template(db, ctx, template_id)
    await _ensure_template_history_seeded(db, ctx, template)

    stmt = (
        select(TemplateAutomationSend)
        .where(
            TemplateAutomationSend.template_id == template.id,
            TemplateAutomationSend.practice_id == ctx.practice_id,
            TemplateAutomationSend.location_id == ctx.location_id,
        )
        .order_by(TemplateAutomationSend.sent_at.desc())
    )
    if q and q.strip():
        needle = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                TemplateAutomationSend.patient_name.ilike(needle),
                TemplateAutomationSend.communication_label.ilike(needle),
                TemplateAutomationSend.provider_name.ilike(needle),
            )
        )
    if sent_from is not None:
        start = datetime(sent_from.year, sent_from.month, sent_from.day, tzinfo=timezone.utc)
        stmt = stmt.where(TemplateAutomationSend.sent_at >= start)
    if sent_to is not None:
        end = datetime(
            sent_to.year, sent_to.month, sent_to.day, 23, 59, 59, tzinfo=timezone.utc
        )
        stmt = stmt.where(TemplateAutomationSend.sent_at <= end)

    return list(await db.scalars(stmt.limit(200)))


_DEFAULT_SAVED_RESPONSES = [
    {
        "title": "Appointment Rescheduled",
        "body": (
            "Hi {{PATIENT_FIRST_NAME}}, your appointment has been rescheduled. "
            "Reply if you have any questions — {{LOCATION_PHONE}}"
        ),
    },
    {
        "title": "APPT",
        "body": "Hi {{PATIENT_FIRST_NAME}}, here are your appointment details. See you soon!",
    },
    {
        "title": "APPT TIME",
        "body": "Hi {{PATIENT_FIRST_NAME}}, just confirming your upcoming visit.",
    },
]


async def list_saved_responses(
    db: AsyncSession, ctx: StaffContext, *, q: str | None = None
) -> list[SavedResponse]:
    """Responses owned by this location or shared with it."""
    loc_id = str(ctx.location_id)
    rows = list(
        await db.scalars(
            select(SavedResponse)
            .where(SavedResponse.practice_id == ctx.practice_id)
            .order_by(SavedResponse.title.asc())
        )
    )
    visible: list[SavedResponse] = []
    for row in rows:
        shared = [str(x) for x in (row.shared_location_ids or [])]
        if row.location_id == ctx.location_id or loc_id in shared:
            visible.append(row)

    owned = [r for r in rows if r.location_id == ctx.location_id]
    if not owned:
        # Seed defaults for this location on first visit
        seeded: list[SavedResponse] = []
        for spec in _DEFAULT_SAVED_RESPONSES:
            row = SavedResponse(
                practice_id=ctx.practice_id,
                location_id=ctx.location_id,
                title=spec["title"],
                body=spec["body"],
                shared_location_ids=[],
            )
            db.add(row)
            seeded.append(row)
        await db.commit()
        for row in seeded:
            await db.refresh(row)
        visible = seeded + [r for r in visible if r.location_id != ctx.location_id]

    if q and q.strip():
        needle = q.strip().lower()
        visible = [
            r
            for r in visible
            if needle in r.title.lower() or needle in (r.body or "").lower()
        ]
    return visible


async def create_saved_response(
    db: AsyncSession, ctx: StaffContext, data: SavedResponseCreate
) -> SavedResponse:
    shared = [lid for lid in data.shared_location_ids if lid != ctx.location_id]
    row = SavedResponse(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        title=data.title.strip(),
        body=data.body or "",
        shared_location_ids=[str(x) for x in shared],
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _get_saved_response(
    db: AsyncSession, ctx: StaffContext, response_id: uuid.UUID
) -> SavedResponse:
    row = await db.scalar(
        select(SavedResponse).where(
            SavedResponse.id == response_id,
            SavedResponse.practice_id == ctx.practice_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved response not found")
    # Only owner location can edit/delete
    if row.location_id != ctx.location_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owning location can edit this saved response",
        )
    return row


async def update_saved_response(
    db: AsyncSession,
    ctx: StaffContext,
    response_id: uuid.UUID,
    data: SavedResponseUpdate,
) -> SavedResponse:
    row = await _get_saved_response(db, ctx, response_id)
    payload = data.model_dump(exclude_unset=True)
    if "title" in payload and payload["title"] is not None:
        row.title = payload["title"].strip()
    if "body" in payload and payload["body"] is not None:
        row.body = payload["body"]
    if "shared_location_ids" in payload and payload["shared_location_ids"] is not None:
        row.shared_location_ids = [
            str(x) for x in payload["shared_location_ids"] if x != ctx.location_id
        ]
    await db.commit()
    await db.refresh(row)
    return row


async def delete_saved_response(
    db: AsyncSession, ctx: StaffContext, response_id: uuid.UUID
) -> None:
    row = await _get_saved_response(db, ctx, response_id)
    await db.delete(row)
    await db.commit()


OOO_THROTTLE_MINUTES = 30


def _parse_hhmm(value: str | None) -> time:
    if not value:
        return time(9, 0)
    parts = value.strip().split(":")
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        return time(h, m)
    except (ValueError, IndexError):
        return time(9, 0)


def _time_in_range(now_t: time, start_s: str | None, end_s: str | None) -> bool:
    start = _parse_hhmm(start_s)
    end = _parse_hhmm(end_s)
    if start <= end:
        return start <= now_t < end
    # Overnight window
    return now_t >= start or now_t < end


def is_outside_service_hours(settings: OutOfOfficeSettings, when: datetime | None = None) -> bool:
    """True when inbound SMS should get an out-of-office auto-reply."""
    now = when or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now  # demo uses UTC as practice local time
    today = local.date().isoformat()

    for cd in settings.custom_dates or []:
        if str(cd.get("date") or "") != today:
            continue
        if cd.get("unavailable"):
            return True
        return not _time_in_range(local.time().replace(tzinfo=None), cd.get("start"), cd.get("end"))

    # Python weekday: Mon=0 … Sun=6 → our day: Sun=0 … Sat=6
    our_day = (local.weekday() + 1) % 7
    hours_list = settings.service_hours or DEFAULT_SERVICE_HOURS
    hours = next((h for h in hours_list if int(h.get("day", -1)) == our_day), None)
    if hours is None:
        return True
    if hours.get("unavailable"):
        return True
    return not _time_in_range(
        local.time().replace(tzinfo=None), hours.get("start"), hours.get("end")
    )


async def _ensure_ooo_row(db: AsyncSession, ctx: StaffContext) -> OutOfOfficeSettings:
    row = await db.scalar(
        select(OutOfOfficeSettings).where(
            OutOfOfficeSettings.practice_id == ctx.practice_id,
            OutOfOfficeSettings.location_id == ctx.location_id,
        )
    )
    if row is not None:
        if not row.service_hours:
            row.service_hours = list(DEFAULT_SERVICE_HOURS)
            await db.commit()
            await db.refresh(row)
        return row

    row = OutOfOfficeSettings(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        enabled=False,
        auto_reply_message=DEFAULT_OOO_MESSAGE,
        service_hours=list(DEFAULT_SERVICE_HOURS),
        custom_dates=[],
        shared_location_ids=[],
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def get_out_of_office_settings(
    db: AsyncSession, ctx: StaffContext
) -> OutOfOfficeSettings:
    return await _ensure_ooo_row(db, ctx)


async def update_out_of_office_settings(
    db: AsyncSession, ctx: StaffContext, data: OutOfOfficeSettingsUpdate
) -> OutOfOfficeSettings:
    row = await _ensure_ooo_row(db, ctx)
    payload = data.model_dump(exclude_unset=True)
    if "enabled" in payload and payload["enabled"] is not None:
        row.enabled = bool(payload["enabled"])
    if "auto_reply_message" in payload and payload["auto_reply_message"] is not None:
        msg = (payload["auto_reply_message"] or "").strip()
        if not msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Auto-reply message cannot be empty",
            )
        row.auto_reply_message = msg[:320]
    if "service_hours" in payload and payload["service_hours"] is not None:
        row.service_hours = [
            {
                "day": int(d["day"]),
                "unavailable": bool(d.get("unavailable")),
                "start": d.get("start") or "09:00",
                "end": d.get("end") or "17:00",
            }
            for d in payload["service_hours"]
        ]
    if "custom_dates" in payload and payload["custom_dates"] is not None:
        row.custom_dates = [
            {
                "id": str(d.get("id") or uuid.uuid4()),
                "date": str(d["date"]),
                "label": (d.get("label") or "")[:200],
                "unavailable": bool(d.get("unavailable", True)),
                "start": d.get("start") or "09:00",
                "end": d.get("end") or "17:00",
            }
            for d in payload["custom_dates"]
        ]
    if "shared_location_ids" in payload and payload["shared_location_ids"] is not None:
        row.shared_location_ids = [
            str(x) for x in payload["shared_location_ids"] if x != ctx.location_id
        ]
    await db.commit()
    await db.refresh(row)
    return row


async def get_effective_ooo_for_location(
    db: AsyncSession, practice_id: uuid.UUID, location_id: uuid.UUID
) -> OutOfOfficeSettings | None:
    """Own settings, or settings shared to this location from another location."""
    own = await db.scalar(
        select(OutOfOfficeSettings).where(
            OutOfOfficeSettings.practice_id == practice_id,
            OutOfOfficeSettings.location_id == location_id,
        )
    )
    if own is not None and own.enabled:
        return own

    rows = list(
        await db.scalars(
            select(OutOfOfficeSettings).where(
                OutOfOfficeSettings.practice_id == practice_id,
                OutOfOfficeSettings.enabled.is_(True),
            )
        )
    )
    loc = str(location_id)
    for row in rows:
        if loc in [str(x) for x in (row.shared_location_ids or [])]:
            return row
    return own  # may be disabled; caller checks enabled


_SMS_FORM_FIELDS = (
    "legal_business_name",
    "ein",
    "dba_name",
    "business_type",
    "business_address",
    "business_city",
    "business_state",
    "business_zip",
    "business_phone",
    "business_website",
    "auth_rep_name",
    "auth_rep_email",
    "auth_rep_phone",
    "auth_rep_title",
    "office_phone_number",
)


async def _ensure_sms_registration(db: AsyncSession, ctx: StaffContext) -> SmsRegistration:
    row = await db.scalar(
        select(SmsRegistration).where(
            SmsRegistration.practice_id == ctx.practice_id,
            SmsRegistration.location_id == ctx.location_id,
        )
    )
    if row is not None:
        return row

    location = await db.scalar(select(Location).where(Location.id == ctx.location_id))
    row = SmsRegistration(
        practice_id=ctx.practice_id,
        location_id=ctx.location_id,
        status=SmsRegistrationStatus.NOT_STARTED.value,
        legal_business_name=(location.name if location else "") or "",
        business_address=(location.address if location else "") or "",
        business_city=(location.city if location else "") or "",
        business_state=(location.state if location else "") or "",
        business_zip=(location.zip_code if location else "") or "",
        business_phone=(location.phone if location else "") or "",
        office_phone_number=(location.phone if location else "") or "",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def get_sms_registration(db: AsyncSession, ctx: StaffContext) -> SmsRegistration:
    return await _ensure_sms_registration(db, ctx)


async def is_sms_registration_approved(
    db: AsyncSession, practice_id: uuid.UUID, location_id: uuid.UUID
) -> bool:
    row = await db.scalar(
        select(SmsRegistration).where(
            SmsRegistration.practice_id == practice_id,
            SmsRegistration.location_id == location_id,
        )
    )
    return row is not None and row.status == SmsRegistrationStatus.APPROVED.value


async def update_sms_registration(
    db: AsyncSession, ctx: StaffContext, data: SmsRegistrationUpdate
) -> SmsRegistration:
    row = await _ensure_sms_registration(db, ctx)
    if row.status == SmsRegistrationStatus.IN_PROGRESS.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration is In Progress and cannot be edited until review completes",
        )
    if row.status == SmsRegistrationStatus.APPROVED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration is already approved",
        )

    payload = data.model_dump(exclude_unset=True)
    for key in _SMS_FORM_FIELDS:
        if key in payload and payload[key] is not None:
            setattr(row, key, str(payload[key]).strip())
    if "request_office_number_hosting" in payload and payload["request_office_number_hosting"] is not None:
        row.request_office_number_hosting = bool(payload["request_office_number_hosting"])

    if row.status == SmsRegistrationStatus.FAILED.value:
        # Editing a failed registration keeps failed until resubmit
        pass
    elif row.status == SmsRegistrationStatus.NOT_STARTED.value:
        # Stay not_started until explicit submit
        pass

    await db.commit()
    await db.refresh(row)
    return row


async def submit_sms_registration(db: AsyncSession, ctx: StaffContext) -> SmsRegistration:
    row = await _ensure_sms_registration(db, ctx)
    if row.status == SmsRegistrationStatus.APPROVED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Registration is already approved"
        )
    if row.status == SmsRegistrationStatus.IN_PROGRESS.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration is already In Progress",
        )

    required = {
        "legal_business_name": row.legal_business_name,
        "ein": row.ein,
        "business_address": row.business_address,
        "business_city": row.business_city,
        "business_state": row.business_state,
        "business_zip": row.business_zip,
        "business_phone": row.business_phone,
        "auth_rep_name": row.auth_rep_name,
        "auth_rep_email": row.auth_rep_email,
        "auth_rep_phone": row.auth_rep_phone,
        "auth_rep_title": row.auth_rep_title,
    }
    missing = [k for k, v in required.items() if not (v or "").strip()]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Complete required fields before submitting: {', '.join(missing)}",
        )

    row.status = SmsRegistrationStatus.IN_PROGRESS.value
    row.submitted_at = datetime.now(timezone.utc)
    row.reviewed_at = None
    row.failure_reason = ""
    await db.commit()
    await db.refresh(row)
    return row


async def set_sms_registration_status(
    db: AsyncSession, ctx: StaffContext, data: SmsRegistrationStatusUpdate
) -> SmsRegistration:
    """Demo helper to approve/fail a registration under review."""
    row = await _ensure_sms_registration(db, ctx)
    status_val = data.status
    if status_val == SmsRegistrationStatus.APPROVED.value:
        row.status = SmsRegistrationStatus.APPROVED.value
        row.failure_reason = ""
        row.reviewed_at = datetime.now(timezone.utc)
    elif status_val == SmsRegistrationStatus.FAILED.value:
        row.status = SmsRegistrationStatus.FAILED.value
        row.failure_reason = (
            (data.failure_reason or "").strip()
            or "Business details could not be verified. Confirm your full legal business name and EIN match your tax documentation, then resubmit."
        )
        row.reviewed_at = datetime.now(timezone.utc)
    elif status_val == SmsRegistrationStatus.IN_PROGRESS.value:
        row.status = SmsRegistrationStatus.IN_PROGRESS.value
        row.failure_reason = ""
        if row.submitted_at is None:
            row.submitted_at = datetime.now(timezone.utc)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")
    await db.commit()
    await db.refresh(row)
    return row
