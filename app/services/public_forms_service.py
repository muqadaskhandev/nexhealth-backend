"""Business logic for the public (unauthenticated) patient forms portal."""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.models.location import Location
from app.models.practice import Practice
from app.models.staff import ActivityType, FormAccessToken, FormRequest, FormRequestStatus, FormSubmission, FormTemplate, Patient
from app.services.staff_service import FORM_REQUEST_EXPIRY_GRACE_HOURS, _log_activity, _now

_GRACE = timedelta(hours=FORM_REQUEST_EXPIRY_GRACE_HOURS)


async def get_token(db: AsyncSession, raw_token: str) -> FormAccessToken | None:
    result = await db.execute(
        select(FormAccessToken).where(FormAccessToken.token_hash == security.hash_token(raw_token))
    )
    token = result.scalar_one_or_none()
    if token is None:
        return None
    if token.expires_at < _now():
        return None
    return token


async def get_branding(db: AsyncSession, token: FormAccessToken) -> dict:
    practice = await db.get(Practice, token.practice_id)
    location = await db.get(Location, token.location_id)
    return {
        "practice_name": practice.name if practice else "",
        "practice_logo_url": practice.logo_url if practice else None,
        "location_name": location.name if location else "",
        "location_address": ", ".join(p for p in [location.address if location else "", location.city if location else ""] if p),
        "location_phone": location.phone if location else "",
    }


async def verify_patient(db: AsyncSession, token: FormAccessToken, last_name: str, dob) -> Patient | None:
    patient = await db.get(Patient, token.patient_id)
    if patient is None:
        return None
    if patient.last_name.strip().lower() != last_name.strip().lower():
        return None
    if patient.dob is None or patient.dob != dob:
        return None
    return patient


async def list_pending_forms(db: AsyncSession, patient: Patient) -> list[dict]:
    now = _now()
    result = await db.execute(
        select(FormRequest, FormTemplate)
        .join(FormTemplate, FormTemplate.id == FormRequest.form_template_id)
        .where(
            FormRequest.patient_id == patient.id,
            FormRequest.archived_at.is_(None),
        )
        .order_by(FormTemplate.name.asc())
    )
    rows = result.all()
    out: list[dict] = []
    for req, tpl in rows:
        completed = req.status == FormRequestStatus.COMPLETED
        if not completed and now > req.expires_at + _GRACE:
            continue
        out.append(
            {
                "request_id": req.id,
                "template_id": tpl.id,
                "name": tpl.name,
                "display_type": tpl.display_type,
                "page_count": tpl.page_count,
                "fields": tpl.fields,
                "completed": completed,
                "expires_at": req.expires_at,
            }
        )
    return out


async def submit_form(
    db: AsyncSession, patient: Patient, form_request_id: uuid.UUID, answers: dict
) -> int:
    result = await db.execute(
        select(FormRequest).where(
            FormRequest.id == form_request_id,
            FormRequest.patient_id == patient.id,
            FormRequest.archived_at.is_(None),
        )
    )
    req = result.scalar_one_or_none()
    if req is None:
        raise ValueError("Form request not found")
    if req.status == FormRequestStatus.COMPLETED:
        raise ValueError("This form has already been submitted")
    now = _now()
    if now > req.expires_at + _GRACE:
        raise ValueError("This form has expired — please contact the practice for a new link")

    tpl = await db.get(FormTemplate, req.form_template_id)
    req.status = FormRequestStatus.COMPLETED

    db.add(
        FormSubmission(
            form_request_id=req.id,
            patient_id=patient.id,
            form_name=tpl.name if tpl else "",
            device="web",
            sync_status="complete",
            answers=answers,
        )
    )
    await _log_activity(
        db,
        patient_id=patient.id,
        activity_type=ActivityType.FORM,
        title=f"Form completed — {tpl.name if tpl else ''}",
    )
    await db.flush()

    result = await db.execute(
        select(FormRequest).where(
            FormRequest.patient_id == patient.id,
            FormRequest.archived_at.is_(None),
            FormRequest.status != FormRequestStatus.COMPLETED,
            FormRequest.expires_at >= now - _GRACE,
        )
    )
    remaining = len(result.scalars().all())
    return remaining
