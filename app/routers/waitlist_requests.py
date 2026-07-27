"""Waitlist requests: batched time-slot offers sent to candidate patients."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_context import StaffContext, get_staff_context
from app.database import get_db
from app.models.waitlist import WaitlistRequest
from app.models.providers import Operatory, Provider
from app.config import settings
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


async def _slot_outs(db: AsyncSession, slots) -> list[WaitlistRequestSlotOut]:
    out: list[WaitlistRequestSlotOut] = []
    for s in slots:
        provider = await db.get(Provider, s.provider_id)
        operatory = await db.get(Operatory, s.operatory_id) if s.operatory_id else None
        out.append(
            WaitlistRequestSlotOut(
                id=s.id,
                provider_id=s.provider_id,
                operatory_id=s.operatory_id,
                provider_name=provider.name if provider else "",
                operatory_name=operatory.name if operatory else None,
                starts_at=s.starts_at,
                ends_at=s.ends_at,
                claimed_by_patient_id=s.claimed_by_patient_id,
                claimed_at=s.claimed_at,
                created_appointment_id=s.created_appointment_id,
                cancelled_at=s.cancelled_at,
            )
        )
    return out


async def _to_out(db: AsyncSession, request: WaitlistRequest) -> WaitlistRequestOut:
    slots = await waitlist_requests_service.get_slots(db, request.id)
    patients = await waitlist_requests_service.get_patients(db, request.id)
    return WaitlistRequestOut(
        id=request.id,
        status=request.status.value,
        template_type=request.template_type,
        created_at=request.created_at,
        sent_at=request.sent_at,
        slots=await _slot_outs(db, slots),
        patients=[
            WaitlistPatientOut(
                id=wp.id,
                patient_id=wp.patient_id,
                name=f"{p.first_name} {p.last_name}".strip(),
                notified_at=wp.notified_at,
                scheduled_notify_at=wp.scheduled_notify_at,
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
        request = await waitlist_requests_service.create_and_send_request(
            db, ctx, payload, booking_base_url=settings.frontend_url
        )
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


@router.get("/api/waitlist-requests/candidates/asap", response_model=list[PatientCandidateOut])
async def search_asap_candidates(
    provider_id: uuid.UUID | None = Query(default=None),
    operatory_id: uuid.UUID | None = Query(default=None),
    appointment_type_id: uuid.UUID | None = Query(default=None),
    duration_minutes: int | None = Query(default=None, ge=5),
    exclude_recent_days: int = Query(default=30, ge=0),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    rows = await waitlist_requests_service.search_asap(
        db,
        ctx,
        provider_id=provider_id,
        operatory_id=operatory_id,
        appointment_type_id=appointment_type_id,
        duration_minutes=duration_minutes,
        exclude_recent_days=exclude_recent_days,
    )
    return [
        PatientCandidateOut(
            id=patient.id,
            name=f"{patient.first_name} {patient.last_name}".strip(),
            reason="asap",
            appointment_at=appt.starts_at,
            appointment_notes=str((appt.meta or {}).get("notes", "") or ""),
        )
        for patient, appt in rows
    ]


@router.get("/api/waitlist-requests/candidates/continuing-care", response_model=list[PatientCandidateOut])
async def search_continuing_care_candidates(
    recall_type: str | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    exclude_recent_days: int = Query(default=30, ge=0),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        patients = await waitlist_requests_service.search_continuing_care(
            db,
            ctx,
            recall_type=recall_type,
            start_date=start_date,
            end_date=end_date,
            exclude_recent_days=exclude_recent_days,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    results: list[PatientCandidateOut] = []
    for p in patients:
        recall = (p.meta or {}).get("recall") or {}
        due_raw = recall.get("due_date")
        recall_due: date | None = None
        if due_raw:
            try:
                recall_due = date.fromisoformat(str(due_raw)[:10])
            except ValueError:
                recall_due = None
        results.append(
            PatientCandidateOut(
                id=p.id,
                name=f"{p.first_name} {p.last_name}".strip(),
                reason="continuing_care",
                recall_type=str(recall.get("type", "")) or None,
                recall_due_date=recall_due,
            )
        )
    return results


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


@router.post("/api/waitlist-requests/{request_id}/slots/{slot_id}/cancel", response_model=WaitlistRequestOut)
async def cancel_waitlist_slot(
    request_id: uuid.UUID,
    slot_id: uuid.UUID,
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
        await waitlist_requests_service.cancel_slot(db, request, slot)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
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
