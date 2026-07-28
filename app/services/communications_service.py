"""Communication templates service — list, activate, edit steps, sending hours."""
from __future__ import annotations

import uuid
from datetime import time

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.staff_context import StaffContext
from app.models.communications import (
    CommunicationTemplate,
    CommunicationTemplateStep,
    TemplateCategory,
    TemplateConfiguration,
    TemplateStepKind,
)
from app.models.location import Location
from app.schemas.communications import (
    CommunicationTemplateUpdate,
    TemplateConfigurationUpdate,
    TemplateStepCreate,
    TemplateStepUpdate,
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
        "description": "Sent when a new appointment is scheduled on your practice management calendar (e.g. phone or front desk). Deduped to the same phone and patient name once every 6 hours.",
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
                "body": "Hi {{PATIENT_FIRST_NAME}}, reminder: your appointment at {{LOCATION_NAME}} is on {{APPOINTMENT_DATE}} at {{APPOINTMENT_TIME}}.",
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
        "description": "Sent when a new patient is added to your health record system. NexHealth checks every 15 minutes between 8 AM and 7 PM. Sends on patient create, not on booking.",
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


async def list_templates(db: AsyncSession, ctx: StaffContext) -> list[CommunicationTemplate]:
    await _ensure_templates_seeded(db, ctx)
    loc = await db.get(Location, ctx.location_id)
    location_name = loc.name if loc else ""

    result = await db.scalars(
        select(CommunicationTemplate)
        .where(CommunicationTemplate.location_id == ctx.location_id)
        .options(selectinload(CommunicationTemplate.steps))
        .order_by(CommunicationTemplate.name)
    )
    rows = list(result)
    for row in rows:
        row.location_name = location_name  # type: ignore[attr-defined]
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
    return tmpl


async def get_template_by_slug(db: AsyncSession, ctx: StaffContext, slug: str) -> CommunicationTemplate:
    await _ensure_templates_seeded(db, ctx)
    tmpl = await db.scalar(
        select(CommunicationTemplate)
        .where(
            CommunicationTemplate.slug == slug,
            CommunicationTemplate.location_id == ctx.location_id,
        )
        .options(selectinload(CommunicationTemplate.steps))
    )
    if not tmpl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    loc = await db.get(Location, ctx.location_id)
    tmpl.location_name = loc.name if loc else ""  # type: ignore[attr-defined]
    return tmpl


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
    if data.sending_hours_end <= data.sending_hours_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End time must be after start time",
        )
    config.sending_hours_start = data.sending_hours_start
    config.sending_hours_end = data.sending_hours_end
    await db.commit()
    await db.refresh(config)
    return config
