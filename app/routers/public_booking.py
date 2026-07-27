"""Public (unauthenticated) online booking portal routes.

NOTE: no `from __future__ import annotations` — slowapi + FastAPI body parsing
(see app/routers/public_forms.py).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.public_booking import (
    PublicBookOut,
    PublicBookRequest,
    PublicBookingFormFieldOut,
    PublicBookingInfoOut,
    PublicBookingInsuranceOut,
    PublicBookingLocationOut,
    PublicBookingOpeningOut,
    PublicBookingProviderOut,
    PublicBookingTypeOut,
)
from app.services import google_reserve_service, public_booking_service
from app.services.public_booking_service import PatientNotFoundError

router = APIRouter(tags=["public-booking"])
limiter = Limiter(key_func=get_remote_address)


@router.get("/api/public/booking/{slug}", response_model=PublicBookingInfoOut)
async def get_booking_info(
    slug: str,
    lid: str | None = Query(default=None),
    location_ids: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    info = await public_booking_service.get_booking_info(
        db, slug=slug, lid=lid, location_ids_raw=location_ids
    )
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Online booking is not available for this practice.")
    return PublicBookingInfoOut(**info)


@router.get("/api/public/booking/{slug}/types", response_model=list[PublicBookingTypeOut])
async def list_types(
    slug: str,
    location_id: uuid.UUID = Query(...),
    patient_kind: str = Query(default="new", pattern="^(new|existing)$"),
    appointment_type_ids: str | None = Query(default=None),
    lid: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    types = await public_booking_service.list_booking_types(
        db,
        slug=slug,
        location_id=location_id,
        patient_kind=patient_kind,
        appointment_type_ids_raw=appointment_type_ids,
        lid=lid,
    )
    if types is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Location not found.")
    return [
        PublicBookingTypeOut(
            id=t.id,
            name=t.name,
            duration_minutes=t.duration_minutes,
            patient_type=t.patient_type.value,
        )
        for t in types
    ]


@router.get("/api/public/booking/{slug}/providers", response_model=list[PublicBookingProviderOut])
async def list_providers(
    slug: str,
    location_id: uuid.UUID = Query(...),
    appointment_type_id: uuid.UUID = Query(...),
    provider_ids: str | None = Query(default=None),
    lid: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    providers = await public_booking_service.list_booking_providers(
        db,
        slug=slug,
        location_id=location_id,
        appointment_type_id=appointment_type_id,
        provider_ids_raw=provider_ids,
        lid=lid,
    )
    if providers is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Location not found.")
    return [
        PublicBookingProviderOut(id=p.id, name=p.name, role=p.role, avatar_url=p.avatar_url)
        for p in providers
    ]


@router.get("/api/public/booking/{slug}/openings", response_model=list[PublicBookingOpeningOut])
async def list_openings(
    slug: str,
    location_id: uuid.UUID = Query(...),
    appointment_type_id: uuid.UUID = Query(...),
    provider_id: uuid.UUID | None = Query(default=None),
    provider_ids: str | None = Query(default=None),
    days: int = Query(default=14, ge=1, le=30),
    lid: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    openings = await public_booking_service.list_booking_openings(
        db,
        slug=slug,
        location_id=location_id,
        appointment_type_id=appointment_type_id,
        provider_id=provider_id,
        provider_ids_raw=provider_ids,
        days=days,
        lid=lid,
    )
    if openings is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Location not found.")
    return [PublicBookingOpeningOut(date=o["date"], times=o["times"]) for o in openings]


@router.get("/api/public/booking/{slug}/form-fields", response_model=list[PublicBookingFormFieldOut])
async def list_form_fields(
    slug: str,
    location_id: uuid.UUID = Query(...),
    patient_kind: str = Query(default="new", pattern="^(new|existing)$"),
    lid: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    fields = await public_booking_service.list_booking_form_fields(
        db, slug=slug, location_id=location_id, patient_kind=patient_kind, lid=lid
    )
    if fields is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Location not found.")
    return [
        PublicBookingFormFieldOut(
            id=f.id,
            label=f.label,
            field_type=f.field_type.value,
            required=f.required,
            show_to=f.show_to,
            options=f.options or [],
            help_text=f.note_text if f.field_type.value == "note" else "",
        )
        for f in fields
    ]


@router.get("/api/public/booking/{slug}/insurances", response_model=list[PublicBookingInsuranceOut])
async def list_insurances(
    slug: str,
    location_id: uuid.UUID = Query(...),
    lid: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    rows = await public_booking_service.list_booking_insurances(
        db, slug=slug, location_id=location_id, lid=lid
    )
    if rows is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Location not found.")
    return [PublicBookingInsuranceOut(id=r.id, name=r.name) for r in rows]


@router.get("/api/public/booking/{slug}/google-reserve")
async def google_reserve_feed(
    slug: str,
    lid: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Locations enabled for Reserve with Google — used for address matching and booking URLs."""
    rows = await google_reserve_service.get_google_reserve_feed(db, slug=slug, lid=lid)
    if rows is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Practice not found.")
    return {"practice_slug": slug, "locations": rows}


@router.post("/api/public/booking/{slug}/book", response_model=PublicBookOut)
@limiter.limit("10/minute")
async def book(
    request: Request,
    slug: str,
    payload: PublicBookRequest,
    lid: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await public_booking_service.book_appointment(db, slug=slug, payload=payload, lid=lid)
    except PatientNotFoundError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "patient_not_found",
                "message": "We couldn't find your patient record. Please check your information or book as a new patient.",
            },
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Online booking is not available.")
    await db.commit()
    return PublicBookOut(**result)
