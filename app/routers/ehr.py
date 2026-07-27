"""EHR integration endpoints (gated until connectors are live)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.ehr_features import EHR_COMING_SOON_MESSAGE, EHR_FEATURES
from app.core.ehr_gate import require_ehr_sync_enabled
from app.core.staff_context import StaffContext, get_staff_context
from app.database import get_db
from app.schemas.ehr_sync import EhrFeaturesOut
from app.services import appointment_rules_service

router = APIRouter(prefix="/api/ehr", tags=["ehr"])


@router.get("/features", response_model=EhrFeaturesOut)
async def list_ehr_features() -> EhrFeaturesOut:
    features = [
        f.model_copy(update={"status": "available" if settings.ehr_sync_enabled else "coming_soon"})
        for f in EHR_FEATURES
    ]
    return EhrFeaturesOut(
        enabled=settings.ehr_sync_enabled,
        message=EHR_COMING_SOON_MESSAGE if not settings.ehr_sync_enabled else "EHR synchronization is enabled.",
        features=features,
    )


@router.post("/appointments/{appointment_id}/apply-insertion-rules")
async def apply_insertion_rules_to_ehr(
    appointment_id: uuid.UUID,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    require_ehr_sync_enabled()
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented")


@router.post("/appointments/sync-mapping-tags")
async def sync_mapping_tags_from_ehr(
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    require_ehr_sync_enabled()
    updated = await appointment_rules_service.retag_appointments_at_location(
        db, practice_id=ctx.practice_id, location_id=ctx.location_id
    )
    await db.commit()
    return {"updated": updated}
