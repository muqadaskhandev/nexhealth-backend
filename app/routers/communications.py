"""Communication templates and template configuration API."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_context import StaffContext, get_staff_context
from app.database import get_db
from app.schemas.communications import (
    CommunicationTemplateOut,
    CommunicationTemplateUpdate,
    TemplateConfigurationOut,
    TemplateConfigurationUpdate,
    TemplateStepCreate,
    TemplateStepOut,
    TemplateStepUpdate,
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
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    rows = await svc.list_templates(db, ctx)
    return [_template_out(r) for r in rows]


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
