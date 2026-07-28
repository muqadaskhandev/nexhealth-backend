"""Update scheduling when patient form intake completes."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.staff import Appointment, FormsStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def sync_patient_forms_status(
    db: AsyncSession,
    *,
    patient_id: uuid.UUID,
    location_id: uuid.UUID,
    remaining_pending_forms: int,
) -> None:
    """Mark upcoming appointments complete when all active form requests are done."""
    if remaining_pending_forms > 0:
        return

    now = _now()
    result = await db.execute(
        select(Appointment).where(
            Appointment.patient_id == patient_id,
            Appointment.location_id == location_id,
            Appointment.starts_at >= now,
            Appointment.forms_status == FormsStatus.INCOMPLETE,
        )
    )
    for appt in result.scalars().all():
        appt.forms_status = FormsStatus.COMPLETE
    await db.flush()
