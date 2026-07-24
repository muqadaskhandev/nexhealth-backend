"""Waitlist requests: batched time-slot offers sent to candidate patients."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_context import StaffContext, get_staff_context
from app.database import get_db
from app.models.waitlist import WaitlistRequest
from app.schemas.waitlist_requests import (
    ClaimSlotRequest,
    PatientCandidateOut,
    WaitlistPatientOut,
    WaitlistRequestCreate,
    WaitlistRequestOut,
    WaitlistRequestSlotOut,
)
from app.services import waitlist_requests_service

router = APIRouter(tags=["waitlist-requests"])


async def _to_out(db: AsyncSession, request: WaitlistRequest) -> WaitlistRequestOut:
    slots = await waitlist_requests_service.get_slots(db, request.id)
    patients = await waitlist_requests_service.get_patients(db, request.id)
    return WaitlistRequestOut(
        id=request.id,
        status=request.status.value,
        created_at=request.created_at,
        sent_at=request.sent_at,
        slots=[WaitlistRequestSlotOut.model_validate(s) for s in slots],
        patients=[
            WaitlistPatientOut(
                id=wp.id,
                patient_id=wp.patient_id,
                name=f"{p.first_name} {p.last_name}".strip(),
                notified_at=wp.notified_at,
            )
            for wp, p in patients
        ],
    )


@router.get("/api/waitlist-requests", response_model=list[WaitlistRequestOut])
async def list_waitlist_requests(
    ctx: StaffContext = Depends(get_staff_context), db: AsyncSession = Depends(get_db)
):
    requests = await waitlist_requests_service.list_requests(db, ctx)
    return [await _to_out(db, r) for r in requests]


@router.post("/api/waitlist-requests", response_model=WaitlistRequestOut, status_code=status.HTTP_201_CREATED)
async def create_waitlist_request(
    payload: WaitlistRequestCreate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        request = await waitlist_requests_service.create_and_send_request(db, ctx, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return await _to_out(db, request)


@router.get("/api/waitlist-requests/candidates/missed-cancelled", response_model=list[PatientCandidateOut])
async def search_missed_cancelled_candidates(
    missed: bool = Query(default=False),
    cancelled: bool = Query(default=False),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    exclude_recent_days: int = Query(default=30, ge=0),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    rows = await waitlist_requests_service.search_missed_cancelled(
        db,
        ctx,
        missed=missed,
        cancelled=cancelled,
        start_date=start_date,
        end_date=end_date,
        exclude_recent_days=exclude_recent_days,
    )
    return [
        PatientCandidateOut(
            id=patient.id,
            name=f"{patient.first_name} {patient.last_name}".strip(),
            reason="missed" if appt.status.value == "unconfirmed" else "cancelled",
            appointment_at=appt.starts_at,
        )
        for patient, appt in rows
    ]


@router.get("/api/waitlist-requests/{request_id}", response_model=WaitlistRequestOut)
async def get_waitlist_request(
    request_id: uuid.UUID,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    request = await waitlist_requests_service.get_request(db, ctx, request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Waitlist request not found")
    return await _to_out(db, request)


@router.post("/api/waitlist-requests/{request_id}/cancel", response_model=WaitlistRequestOut)
async def cancel_waitlist_request(
    request_id: uuid.UUID,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    request = await waitlist_requests_service.get_request(db, ctx, request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Waitlist request not found")
    request = await waitlist_requests_service.cancel_request(db, request)
    await db.commit()
    return await _to_out(db, request)


@router.post("/api/waitlist-requests/{request_id}/slots/{slot_id}/claim", response_model=WaitlistRequestOut)
async def claim_waitlist_slot(
    request_id: uuid.UUID,
    slot_id: uuid.UUID,
    payload: ClaimSlotRequest,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    request = await waitlist_requests_service.get_request(db, ctx, request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Waitlist request not found")
    slot = await waitlist_requests_service.get_slot(db, request_id, slot_id)
    if slot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Slot not found")
    try:
        await waitlist_requests_service.claim_slot(db, ctx, request, slot, payload.patient_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return await _to_out(db, request)
