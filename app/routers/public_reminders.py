"""Public Reminder confirm / cancel (email registration links)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import reminder_responses as rr

router = APIRouter(tags=["public-reminders"])


class ReminderRespondBody(BaseModel):
    action: str = Field(pattern="^(confirm|cancel)$")
    confirm_cancel: bool = False


@router.get("/api/public/reminders/{appointment_id}")
async def get_reminder_appointment(
    appointment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    return await rr.public_appointment_reminder_info(db, appointment_id)


@router.post("/api/public/reminders/{appointment_id}/respond")
async def respond_to_reminder(
    appointment_id: uuid.UUID,
    body: ReminderRespondBody,
    db: AsyncSession = Depends(get_db),
):
    return await rr.public_respond_to_appointment(
        db,
        appointment_id,
        action=body.action,
        confirm_cancel=body.confirm_cancel,
    )
