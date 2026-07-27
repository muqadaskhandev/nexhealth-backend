"""Public (unauthenticated) waitlist booking — patients claim slots via SMS link."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.waitlist import WaitlistRequestPatient
from app.schemas.waitlist_requests import PublicWaitlistClaimOut, PublicWaitlistOut, PublicWaitlistSlotOut
from app.services import waitlist_requests_service

router = APIRouter(tags=["public-waitlist"])


@router.get("/api/public/waitlist/{token}", response_model=PublicWaitlistOut)
async def get_public_waitlist(token: uuid.UUID, db: AsyncSession = Depends(get_db)):
    data = await waitlist_requests_service.get_public_waitlist(db, token)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This waitlist link is no longer available.")
    return PublicWaitlistOut(
        practice_name=data["practice_name"],
        location_name=data["location_name"],
        patient_first_name=data["patient_first_name"],
        booking_redirect_slug=data["booking_redirect_slug"],
        slots=[PublicWaitlistSlotOut(**s) for s in data["slots"]],
    )


@router.post("/api/public/waitlist/{token}/claim/{slot_id}", response_model=PublicWaitlistClaimOut)
async def claim_public_waitlist_slot(
    token: uuid.UUID,
    slot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WaitlistRequestPatient).where(WaitlistRequestPatient.booking_token == token)
    )
    wp = result.scalar_one_or_none()
    if wp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This waitlist link is no longer available.")

    slot = await waitlist_requests_service.get_slot(db, wp.waitlist_request_id, slot_id)
    if slot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This time slot was not found.")

    try:
        slot = await waitlist_requests_service.claim_slot_public(db, wp, slot)
    except ValueError as exc:
        msg = str(exc)
        if "no longer available" in msg.lower():
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "slot_unavailable",
                    "message": "The time you have selected is no longer available.",
                },
            )
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg)

    await db.commit()
    when = slot.starts_at.strftime("%A, %B %-d at %-I:%M %p")
    return PublicWaitlistClaimOut(
        message="You're all set!",
        appointment_id=slot.created_appointment_id,  # type: ignore[arg-type]
        confirmation=f"Your appointment is booked for {when}.",
    )
