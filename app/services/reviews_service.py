"""Public Reviews survey: 1–5 rating → Google prompt (4–5) or internal feedback (1–3)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.communications import ReviewResponse
from app.models.location import Location
from app.models.staff import Appointment, Patient, PatientActivity, ActivityType

# Default: 4 or 5 receive the Google review prompt. Contact Support to change.
DEFAULT_GOOGLE_MIN_RATING = 4


async def public_review_info(db: AsyncSession, appointment_id: uuid.UUID) -> dict:
    appointment = await db.get(Appointment, appointment_id)
    if not appointment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

    patient = await db.get(Patient, appointment.patient_id)
    loc = await db.get(Location, appointment.location_id)
    location_name = loc.name if loc else "our office"

    existing = await db.scalar(
        select(ReviewResponse)
        .where(ReviewResponse.appointment_id == appointment_id)
        .order_by(ReviewResponse.created_at.desc())
        .limit(1)
    )

    google_url = (
        (appointment.meta or {}).get("google_review_url")
        or (loc and getattr(loc, "website", None))
        or f"https://www.google.com/search?q={location_name.replace(' ', '+')}+reviews"
    )

    return {
        "appointment_id": str(appointment.id),
        "patient_name": (patient.first_name if patient else "there") or "there",
        "location_name": location_name,
        "provider_name": appointment.provider_name or "",
        "appointment_type": appointment.appointment_type or "",
        "starts_at": appointment.starts_at.isoformat(),
        "google_min_rating": DEFAULT_GOOGLE_MIN_RATING,
        "google_review_url": str(google_url),
        "already_rated": existing is not None,
        "prior_rating": existing.rating if existing else None,
        "prior_google_prompted": bool(existing.google_prompted) if existing else False,
        "reviews_enabled": (appointment.meta or {}).get("reviews_enabled", True) is not False,
        "note": (
            "NexHealth does NOT post directly to Google. "
            "The patient must post their review to Google."
        ),
    }


async def public_submit_review(
    db: AsyncSession,
    appointment_id: uuid.UUID,
    *,
    rating: int,
    feedback: str = "",
) -> dict:
    if rating < 1 or rating > 5:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rating must be 1–5")

    appointment = await db.get(Appointment, appointment_id)
    if not appointment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

    if (appointment.meta or {}).get("reviews_enabled") is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reviews are turned off for this appointment",
        )

    patient = await db.get(Patient, appointment.patient_id)
    loc = await db.get(Location, appointment.location_id)
    location_name = loc.name if loc else "our office"

    min_rating = DEFAULT_GOOGLE_MIN_RATING
    google_prompted = rating >= min_rating
    google_url = (
        (appointment.meta or {}).get("google_review_url")
        or f"https://www.google.com/search?q={location_name.replace(' ', '+')}+reviews"
    )

    row = ReviewResponse(
        practice_id=appointment.practice_id,
        location_id=appointment.location_id,
        appointment_id=appointment.id,
        patient_id=appointment.patient_id,
        rating=rating,
        feedback_text=(feedback or "").strip()[:2000],
        google_prompted=google_prompted,
    )
    db.add(row)

    # Activity feed for internal (1–3) feedback and all ratings
    if patient:
        title = f"Review rating: {rating}/5"
        body = (
            f"{patient.first_name} rated their visit {rating}/5."
            + (
                " Prompted to leave a Google review."
                if google_prompted
                else " Internal feedback only (not sent to Google)."
            )
        )
        if feedback and not google_prompted:
            body += f" Feedback: {feedback.strip()[:400]}"
        db.add(
            PatientActivity(
                patient_id=patient.id,
                activity_type=ActivityType.NOTE,
                title=title,
                body=body,
                meta={
                    "appointment_id": str(appointment.id),
                    "rating": rating,
                    "google_prompted": google_prompted,
                    "source": "reviews",
                },
            )
        )

    await db.commit()
    await db.refresh(row)

    if google_prompted:
        return {
            "status": "google_prompt",
            "rating": rating,
            "message": (
                "Thanks for choosing us! We'd appreciate if you could leave us an online review."
            ),
            "google_review_url": str(google_url),
            "sms_followup": (
                f"We're glad to hear you had a good appointment! We'd appreciate if you could "
                f"leave us an online review about your experience: {google_url}"
            ),
            "patient_name": (patient.first_name if patient else "") or "",
            "location_name": location_name,
        }

    return {
        "status": "feedback",
        "rating": rating,
        "message": (
            "We're sorry to hear that. Please let us know what we can do better in the future."
        ),
        "google_review_url": None,
        "sms_followup": (
            "We're sorry to hear that. Please let us know what we can do better in the future."
        ),
        "patient_name": (patient.first_name if patient else "") or "",
        "location_name": location_name,
        "feedback_saved": bool((feedback or "").strip()),
    }


async def list_review_performance(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID,
    location_id: uuid.UUID,
) -> dict:
    rows = list(
        await db.scalars(
            select(ReviewResponse).where(
                ReviewResponse.practice_id == practice_id,
                ReviewResponse.location_id == location_id,
            )
        )
    )
    by_rating = {i: 0 for i in range(1, 6)}
    google = 0
    feedback_count = 0
    for r in rows:
        by_rating[r.rating] = by_rating.get(r.rating, 0) + 1
        if r.google_prompted:
            google += 1
        if (r.feedback_text or "").strip():
            feedback_count += 1
    return {
        "total_ratings": len(rows),
        "by_rating": by_rating,
        "google_prompts": google,
        "internal_feedback": feedback_count,
        "google_min_rating": DEFAULT_GOOGLE_MIN_RATING,
        "recent": [
            {
                "id": str(r.id),
                "rating": r.rating,
                "feedback_text": r.feedback_text,
                "google_prompted": r.google_prompted,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "appointment_id": str(r.appointment_id) if r.appointment_id else None,
            }
            for r in sorted(rows, key=lambda x: x.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[
                :20
            ]
        ],
    }
