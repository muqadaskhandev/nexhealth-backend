"""Communication templates and template configuration API."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_context import StaffContext, get_staff_context
from app.database import get_db
from app.schemas.communications import (
    CommunicationTemplateOut,
    CommunicationTemplateUpdate,
    MessageGroupingPreviewOut,
    MessageGroupingPreviewRequest,
    OtherTemplateDedupeOut,
    OtherTemplateDedupeRequest,
    TemplateAppointmentTypeStatus,
    TemplateConfigurationOut,
    TemplateConfigurationUpdate,
    TemplateStepCreate,
    TemplateStepOut,
    TemplateStepUpdate,
    TemplateVariantToggle,
)
from app.services import communications_service as svc

router = APIRouter(tags=["communications"])


def _template_out(row) -> CommunicationTemplateOut:
    return CommunicationTemplateOut(
        id=row.id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        category=row.category.value if hasattr(row.category, "value") else row.category,
        is_active=row.is_active,
        total_sent=row.total_sent,
        recipients=row.recipients,
        multi_location=row.multi_location,
        appointment_type_id=row.appointment_type_id,
        appointment_type_name=getattr(row, "appointment_type_name", "") or "",
        location_name=getattr(row, "location_name", ""),
        created_at=row.created_at,
        updated_at=row.updated_at,
        steps=[
            TemplateStepOut(
                id=s.id,
                kind=s.kind.value if hasattr(s.kind, "value") else s.kind,
                title=s.title,
                subtitle=s.subtitle,
                body=s.body,
                subject=s.subject,
                timing_value=s.timing_value,
                timing_unit=s.timing_unit,
                condition_label=s.condition_label,
                position=s.position,
                meta=s.meta or {},
            )
            for s in (row.steps or [])
        ],
    )


@router.get("/api/communication-templates", response_model=list[CommunicationTemplateOut])
async def list_templates(
    scope: str = Query("default", pattern="^(default|variants|all)$"),
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    rows = await svc.list_templates(db, ctx, scope=scope)
    return [_template_out(r) for r in rows]


@router.get(
    "/api/communication-templates/by-slug/{slug}/appointment-types",
    response_model=list[TemplateAppointmentTypeStatus],
)
async def list_template_appointment_types(
    slug: str,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    return await svc.list_appointment_type_status(db, ctx, slug)


@router.post(
    "/api/communication-templates/by-slug/{slug}/variants",
    response_model=CommunicationTemplateOut | None,
)
async def set_template_variant(
    slug: str,
    body: TemplateVariantToggle,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    row = await svc.set_variant_for_appointment_type(db, ctx, slug, body)
    return _template_out(row) if row else None


@router.get("/api/communication-templates/by-slug/{slug}", response_model=CommunicationTemplateOut)
async def get_template_by_slug(
    slug: str,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    row = await svc.get_template_by_slug(db, ctx, slug)
    return _template_out(row)


@router.get("/api/communication-templates/{template_id}", response_model=CommunicationTemplateOut)
async def get_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    row = await svc.get_template(db, ctx, template_id)
    return _template_out(row)


@router.patch("/api/communication-templates/{template_id}", response_model=CommunicationTemplateOut)
async def update_template(
    template_id: uuid.UUID,
    body: CommunicationTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    row = await svc.update_template(db, ctx, template_id, body)
    return _template_out(row)


@router.patch(
    "/api/communication-templates/{template_id}/steps/{step_id}",
    response_model=TemplateStepOut,
)
async def update_step(
    template_id: uuid.UUID,
    step_id: uuid.UUID,
    body: TemplateStepUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    step = await svc.update_step(db, ctx, template_id, step_id, body)
    return TemplateStepOut(
        id=step.id,
        kind=step.kind.value if hasattr(step.kind, "value") else step.kind,
        title=step.title,
        subtitle=step.subtitle,
        body=step.body,
        subject=step.subject,
        timing_value=step.timing_value,
        timing_unit=step.timing_unit,
        condition_label=step.condition_label,
        position=step.position,
        meta=step.meta or {},
    )


@router.post(
    "/api/communication-templates/{template_id}/steps",
    response_model=TemplateStepOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_step(
    template_id: uuid.UUID,
    body: TemplateStepCreate,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    step = await svc.add_step(db, ctx, template_id, body)
    return TemplateStepOut(
        id=step.id,
        kind=step.kind.value if hasattr(step.kind, "value") else step.kind,
        title=step.title,
        subtitle=step.subtitle,
        body=step.body,
        subject=step.subject,
        timing_value=step.timing_value,
        timing_unit=step.timing_unit,
        condition_label=step.condition_label,
        position=step.position,
        meta=step.meta or {},
    )


@router.delete(
    "/api/communication-templates/{template_id}/steps/{step_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_step(
    template_id: uuid.UUID,
    step_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    await svc.delete_step(db, ctx, template_id, step_id)


@router.get("/api/template-configurations", response_model=TemplateConfigurationOut)
async def get_template_config(
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    row = await svc.get_or_create_config(db, ctx)
    return TemplateConfigurationOut.model_validate(row)


@router.patch("/api/template-configurations", response_model=TemplateConfigurationOut)
async def update_template_config(
    body: TemplateConfigurationUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    row = await svc.update_config(db, ctx, body)
    return TemplateConfigurationOut.model_validate(row)


@router.get("/api/message-grouping/rules")
async def get_message_grouping_rules(
    ctx: StaffContext = Depends(get_staff_context),
):
    """Help-center copy for how reminders and other templates group messages."""
    from app.services.message_grouping import MESSAGE_GROUPING_RULES_DOC

    return MESSAGE_GROUPING_RULES_DOC


@router.post("/api/message-grouping/preview", response_model=MessageGroupingPreviewOut)
async def preview_message_grouping(
    body: MessageGroupingPreviewRequest,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    """Preview how reminder appointments would be grouped for this location."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from app.models.staff import Appointment, Patient
    from app.services import message_grouping as mg
    from sqlalchemy import select

    config = await svc.get_or_create_config(db, ctx)
    family_on = (
        body.family_messaging_enabled
        if body.family_messaging_enabled is not None
        else config.family_messaging_enabled
    )
    family_reminders = (
        body.use_family_messaging_for_reminders
        if body.use_family_messaging_for_reminders is not None
        else config.use_family_messaging_for_reminders
    )
    journeys = (
        body.appointment_journeys_enabled
        if body.appointment_journeys_enabled is not None
        else config.customize_by_appointment_type
    )

    candidates: list[mg.ReminderAppointment] = []
    if body.appointments:
        for a in body.appointments:
            candidates.append(
                mg.ReminderAppointment(
                    id=a.id or uuid4(),
                    patient_id=a.patient_id,
                    patient_name=a.patient_name,
                    patient_phone=a.patient_phone,
                    guarantor_phone=a.guarantor_phone,
                    starts_at=a.starts_at,
                    duration_minutes=a.duration_minutes,
                    appointment_type=a.appointment_type,
                    journey_key=a.journey_key,
                )
            )
    else:
        day = body.date
        if day is None:
            day = datetime.now(timezone.utc).date()
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        end = start.replace(hour=23, minute=59, second=59)
        result = await db.execute(
            select(Appointment, Patient)
            .join(Patient, Patient.id == Appointment.patient_id)
            .where(
                Appointment.practice_id == ctx.practice_id,
                Appointment.location_id == ctx.location_id,
                Appointment.starts_at >= start,
                Appointment.starts_at <= end,
            )
            .order_by(Appointment.starts_at.asc())
        )
        for appt, patient in result.all():
            candidates.append(
                mg.ReminderAppointment(
                    id=appt.id,
                    patient_id=patient.id,
                    patient_name=f"{patient.first_name} {patient.last_name}".strip(),
                    patient_phone=patient.phone or "",
                    guarantor_phone=(patient.meta or {}).get("guarantor_phone"),
                    starts_at=appt.starts_at,
                    duration_minutes=appt.duration_minutes or 30,
                    appointment_type=appt.appointment_type or "",
                    journey_key=str(appt.appointment_type_def_id)
                    if appt.appointment_type_def_id
                    else appt.appointment_type,
                )
            )

    groups = mg.group_reminder_appointments(
        candidates,
        template_content=body.template_content,
        family_messaging_enabled=family_on,
        use_family_messaging_for_reminders=family_reminders,
        appointment_journeys_enabled=journeys,
    )
    return MessageGroupingPreviewOut(
        consolidation_supported=mg.reminder_supports_consolidation(body.template_content),
        family_messaging_active=bool(family_on and family_reminders),
        groups=[
            MessageGroupOut(
                mode=g.mode,
                recipient_phone=g.recipient_phone,
                recipient_label=g.recipient_label,
                appointment_ids=g.appointment_ids,
                listed_appointment_ids=g.listed_appointment_ids,
                patient_names=g.patient_names,
                notes=g.notes,
                confirm_applies_to_all=g.confirm_applies_to_all,
            )
            for g in groups
        ],
    )


@router.post("/api/message-grouping/other-template-dedupe", response_model=OtherTemplateDedupeOut)
async def other_template_dedupe(
    body: OtherTemplateDedupeRequest,
    ctx: StaffContext = Depends(get_staff_context),
):
    from datetime import datetime, timezone

    from app.services import message_grouping as mg

    decision = mg.other_template_send_decision(
        template_slug=body.template_slug,
        content=body.content,
        phone=body.phone,
        patient_name=body.patient_name,
        now=body.now or datetime.now(timezone.utc),
        last_sent_at=body.last_sent_at,
        mentioned_appointment_count=body.mentioned_appointment_count,
    )
    return OtherTemplateDedupeOut(
        should_send=decision.should_send,
        reason=decision.reason,
        confirm_applies_to_all_mentioned=decision.confirm_applies_to_all_mentioned,
    )
