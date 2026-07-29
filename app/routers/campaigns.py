"""Campaigns API — list, copy, audience, build, send/schedule."""
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_context import StaffContext, get_staff_context
from app.database import get_db
from app.schemas.campaigns import (
    CampaignAudiencePatient,
    CampaignAudiencePreviewOut,
    CampaignCopyRequest,
    CampaignCreateBlank,
    CampaignGenerateAiOut,
    CampaignGenerateAiRequest,
    CampaignImage,
    CampaignOut,
    CampaignScheduleRequest,
    CampaignSendTestRequest,
    CampaignUpdate,
)
from app.services import campaigns_service as svc

router = APIRouter(tags=["campaigns"])


def _campaign_out(row) -> CampaignOut:
    locs: list[uuid.UUID] = []
    for raw in row.location_ids or []:
        try:
            locs.append(uuid.UUID(str(raw)))
        except ValueError:
            continue
    selected: list[uuid.UUID] = []
    for raw in row.selected_patient_ids or []:
        try:
            selected.append(uuid.UUID(str(raw)))
        except ValueError:
            continue
    excluded: list[uuid.UUID] = []
    for raw in row.excluded_patient_ids or []:
        try:
            excluded.append(uuid.UUID(str(raw)))
        except ValueError:
            continue
    images: list[CampaignImage] = []
    for img in row.email_images or []:
        if isinstance(img, dict):
            images.append(
                CampaignImage(
                    id=str(img.get("id") or ""),
                    name=str(img.get("name") or ""),
                    data_url=str(img.get("data_url") or ""),
                    alt=str(img.get("alt") or ""),
                    width=img.get("width"),
                    height=img.get("height"),
                    link_url=str(img.get("link_url") or ""),
                )
            )
    return CampaignOut(
        id=row.id,
        practice_id=row.practice_id,
        location_ids=locs,
        title=row.title or "",
        status=row.status,
        is_favorite_template=bool(row.is_favorite_template),
        source_campaign_id=row.source_campaign_id,
        wizard_step=row.wizard_step or "audience",
        audience_filters=row.audience_filters or {},
        selected_patient_ids=selected,
        excluded_patient_ids=excluded,
        has_email=bool(row.has_email),
        email_subject=row.email_subject or "",
        email_preview_text=row.email_preview_text or "",
        email_body=row.email_body or "",
        email_images=images,
        has_sms=bool(row.has_sms),
        sms_body=row.sms_body or "",
        ai_prompt=row.ai_prompt or "",
        scheduled_at=row.scheduled_at,
        sent_at=row.sent_at,
        recipient_count=int(row.recipient_count or 0),
        created_by_user_id=row.created_by_user_id,
        created_by_name=row.created_by_name or "",
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/api/campaigns", response_model=list[CampaignOut])
async def list_campaigns(
    tab: str = Query(default="all"),
    q: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    rows = await svc.list_campaigns(db, ctx, tab=tab, q=q)
    return [_campaign_out(r) for r in rows]


@router.post("/api/campaigns", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CampaignCreateBlank,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    row = await svc.create_blank_campaign(db, ctx, body)
    return _campaign_out(row)


@router.get("/api/campaigns/{campaign_id}", response_model=CampaignOut)
async def get_campaign(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    row = await svc.get_campaign(db, ctx, campaign_id)
    return _campaign_out(row)


@router.post(
    "/api/campaigns/{campaign_id}/copy",
    response_model=CampaignOut,
    status_code=status.HTTP_201_CREATED,
)
async def copy_campaign(
    campaign_id: uuid.UUID,
    body: CampaignCopyRequest,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    row = await svc.copy_campaign(db, ctx, campaign_id, body)
    return _campaign_out(row)


@router.patch("/api/campaigns/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: uuid.UUID,
    body: CampaignUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    row = await svc.update_campaign(db, ctx, campaign_id, body)
    return _campaign_out(row)


@router.delete("/api/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    await svc.delete_campaign(db, ctx, campaign_id)


@router.get(
    "/api/campaigns/{campaign_id}/audience",
    response_model=CampaignAudiencePreviewOut,
)
async def preview_audience(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    patients, total = await svc.preview_audience(db, ctx, campaign_id)
    return CampaignAudiencePreviewOut(
        total=total,
        patients=[
            CampaignAudiencePatient(
                id=p.id,
                first_name=p.first_name or "",
                last_name=p.last_name or "",
                email=p.email or "",
                phone=p.phone or "",
                dob=p.dob.isoformat() if p.dob else None,
            )
            for p in patients[:500]
        ],
    )


@router.post(
    "/api/campaigns/{campaign_id}/generate-ai",
    response_model=CampaignGenerateAiOut,
)
async def generate_ai(
    campaign_id: uuid.UUID,
    body: CampaignGenerateAiRequest,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    await svc.get_campaign(db, ctx, campaign_id)
    result = svc.generate_ai_copy(body)
    return CampaignGenerateAiOut(**result)


@router.post("/api/campaigns/{campaign_id}/send", response_model=CampaignOut)
async def send_campaign(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    row = await svc.send_campaign_now(db, ctx, campaign_id)
    return _campaign_out(row)


@router.post("/api/campaigns/{campaign_id}/schedule", response_model=CampaignOut)
async def schedule_campaign(
    campaign_id: uuid.UUID,
    body: CampaignScheduleRequest,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    row = await svc.schedule_campaign(db, ctx, campaign_id, body)
    return _campaign_out(row)


@router.post("/api/campaigns/{campaign_id}/send-test")
async def send_test(
    campaign_id: uuid.UUID,
    body: CampaignSendTestRequest,
    db: AsyncSession = Depends(get_db),
    ctx: StaffContext = Depends(get_staff_context),
):
    return await svc.send_test(db, ctx, campaign_id, body.channel)
