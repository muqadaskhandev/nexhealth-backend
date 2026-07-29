"""Patient SMS/email responses to appointment Reminders (confirm / cancel)."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.core.staff_context import StaffContext
from app.models.appointment_types import AppointmentTypeDef
from app.models.practice import Practice
from app.models.staff import Appointment, AppointmentStatus, Patient
from app.services.booking_availability_service import practice_slug


def _set_appt_meta(appt: Appointment, meta: dict) -> None:
    appt.meta = meta
    flag_modified(appt, "meta")

# Auto-confirm when reply is ≤3 words AND contains any of these (help center).
_CONFIRM_KEYWORDS = frozenset(
    {
        "confirm",
        "c",
        "y",
        "yes",
        "k",
        "kk",
        "ok",
        "okay",
        "si",
        "confirmado",
    }
)
_CONFIRM_PHRASES = ("see you soon",)

_CANCEL_KEYWORDS = frozenset({"n", "no", "cancel", "cancelled", "canceled"})


def parse_reminder_reply_intent(text: str) -> str | None:
    """Return 'confirm', 'cancel', or None for non-reminder replies."""
    raw = (text or "").strip()
    if not raw:
        return None
    lowered = raw.lower().strip()
    # Normalize punctuation
    cleaned = re.sub(r"[^\w\s]", " ", lowered)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    words = cleaned.split()
    if not words:
        return None

    # Cancel intent (when enabled — caller checks allow_patient_cancel)
    if len(words) <= 3 and any(w in _CANCEL_KEYWORDS for w in words):
        return "cancel"
    if cleaned in _CANCEL_KEYWORDS:
        return "cancel"

    # Phrase match (counts as multi-word but allowed)
    for phrase in _CONFIRM_PHRASES:
        if phrase in cleaned and len(words) <= 4:
            return "confirm"

    # Auto-confirm: ≤3 words AND contains a confirm keyword
    if len(words) <= 3 and any(w in _CONFIRM_KEYWORDS for w in words):
        return "confirm"

    return None


def insert_confirm_appt_prompt(*, allow_cancel: bool) -> str:
    if allow_cancel:
        return (
            'Reply "Y" to confirm or "N" to cancel your appointment. '
            "You'll receive a link to your forms once you confirm."
        )
    return 'Reply "C" to confirm your appointment. You\'ll receive a link to your forms once you confirm.'


async def _upcoming_appointments_for_patient(
    db: AsyncSession,
    ctx: StaffContext,
    patient_id: uuid.UUID,
) -> list[Appointment]:
    now = datetime.now(timezone.utc)
    rows = list(
        await db.scalars(
            select(Appointment)
            .where(
                Appointment.practice_id == ctx.practice_id,
                Appointment.location_id == ctx.location_id,
                Appointment.patient_id == patient_id,
                Appointment.starts_at >= now,
                Appointment.status.in_(
                    [AppointmentStatus.UNCONFIRMED, AppointmentStatus.CONFIRMED]
                ),
            )
            .order_by(Appointment.starts_at.asc())
        )
    )
    return rows


async def _patient_allows_cancel(
    db: AsyncSession, ctx: StaffContext, appointments: list[Appointment]
) -> bool:
    """True if any upcoming appointment type allows patient cancel from Reminders."""
    type_ids = {a.appointment_type_def_id for a in appointments if a.appointment_type_def_id}
    if type_ids:
        types = list(
            await db.scalars(
                select(AppointmentTypeDef).where(AppointmentTypeDef.id.in_(type_ids))
            )
        )
        if any(t.allow_patient_cancel for t in types):
            return True
    # Fallback: match by name when def id missing
    names = {a.appointment_type for a in appointments if a.appointment_type}
    if names:
        types = list(
            await db.scalars(
                select(AppointmentTypeDef).where(
                    AppointmentTypeDef.location_id == ctx.location_id,
                    AppointmentTypeDef.name.in_(names),
                )
            )
        )
        if any(t.allow_patient_cancel for t in types):
            return True
    return False


async def _booking_link(db: AsyncSession, ctx: StaffContext) -> str:
    practice = await db.get(Practice, ctx.practice_id)
    slug = practice_slug(practice.name) if practice else "book"
    return f"{settings.frontend_url}/appt/{slug}"


async def _send_auto_sms(db: AsyncSession, ctx: StaffContext, patient_id: uuid.UUID, body: str) -> None:
    from app.schemas.staff import SendMessageRequest
    from app.services.staff_service import send_message

    await send_message(
        db, ctx, SendMessageRequest(patient_id=patient_id, body=body, channel="sms")
    )


async def handle_reminder_sms_reply(
    db: AsyncSession,
    ctx: StaffContext,
    patient_id: uuid.UUID,
    text: str,
) -> dict | None:
    """Process confirm/cancel SMS replies. Returns result dict or None if not a reminder reply."""
    intent = parse_reminder_reply_intent(text)
    if intent is None:
        return None

    appointments = await _upcoming_appointments_for_patient(db, ctx, patient_id)
    if not appointments:
        return None

    allow_cancel = await _patient_allows_cancel(db, ctx, appointments)

    # When cancel is disabled, only confirm keywords work (C / Y / etc.) — ignore cancel
    if intent == "cancel" and not allow_cancel:
        return None

    # Pending double-confirm cancel?
    pending = [a for a in appointments if (a.meta or {}).get("cancel_confirm_pending")]
    if pending and intent == "cancel":
        return await _finalize_cancel(db, ctx, patient_id, pending)

    if intent == "cancel" and allow_cancel:
        for appt in appointments:
            meta = dict(appt.meta or {})
            meta["cancel_confirm_pending"] = True
            _set_appt_meta(appt, meta)
        await db.flush()
        await _send_auto_sms(
            db,
            ctx,
            patient_id,
            "Are you sure you want to cancel your appointment? "
            'Reply "N" again to confirm cancellation. Patients are prompted twice before they cancel.',
        )
        return {
            "action": "cancel_prompt",
            "appointment_ids": [str(a.id) for a in appointments],
            "message": "Cancel confirmation prompt sent",
        }

    if intent == "confirm":
        return await _finalize_confirm(db, ctx, patient_id, appointments)

    return None


async def _finalize_confirm(
    db: AsyncSession,
    ctx: StaffContext,
    patient_id: uuid.UUID,
    appointments: list[Appointment],
) -> dict:
    from app.services.staff_service import notify_automatic_forms_on_confirmation

    confirmed_ids: list[str] = []
    for appt in appointments:
        meta = dict(appt.meta or {})
        meta.pop("cancel_confirm_pending", None)
        _set_appt_meta(appt, meta)
        if appt.status == AppointmentStatus.UNCONFIRMED:
            appt.status = AppointmentStatus.CONFIRMED
            confirmed_ids.append(str(appt.id))
            await notify_automatic_forms_on_confirmation(db, ctx, appt)
    await db.flush()

    # Grouping: one reply confirms all appointments reminded on that number/patient
    await _send_auto_sms(
        db,
        ctx,
        patient_id,
        "Thanks — your appointment is confirmed. "
        "If you still have forms to complete, check your messages for the forms link.",
    )
    return {
        "action": "confirm",
        "appointment_ids": confirmed_ids or [str(a.id) for a in appointments],
        "message": "Appointment(s) confirmed",
    }


async def _finalize_cancel(
    db: AsyncSession,
    ctx: StaffContext,
    patient_id: uuid.UUID,
    appointments: list[Appointment],
) -> dict:
    booking = await _booking_link(db, ctx)
    cancelled_ids: list[str] = []
    for appt in appointments:
        meta = dict(appt.meta or {})
        meta.pop("cancel_confirm_pending", None)
        _set_appt_meta(appt, meta)
        if appt.status != AppointmentStatus.CANCELLED:
            appt.status = AppointmentStatus.CANCELLED
            cancelled_ids.append(str(appt.id))
    await db.flush()
    await _send_auto_sms(
        db,
        ctx,
        patient_id,
        f"Your appointment has been cancelled. "
        f"Book a new appointment: {booking}",
    )
    return {
        "action": "cancel",
        "appointment_ids": cancelled_ids,
        "booking_link": booking,
        "message": "Appointment(s) cancelled",
    }


def subsequent_reminder_content_mode(
    *,
    confirmed: bool,
    forms_complete: bool,
    send_to_confirmed: bool,
) -> str:
    """What a later Reminder should contain given patient state (help-center rules)."""
    if not confirmed:
        return "full"  # confirm/cancel + forms
    if confirmed and not forms_complete:
        return "forms_only"
    if confirmed and forms_complete and send_to_confirmed:
        return "full_confirmed_branch"
    return "skip"


async def public_respond_to_appointment(
    db: AsyncSession,
    appointment_id: uuid.UUID,
    *,
    action: str,
    confirm_cancel: bool = False,
) -> dict:
    """Email/web Reminder response: confirm or cancel (with double prompt)."""
    appt = await db.get(Appointment, appointment_id)
    if appt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

    patient = await db.get(Patient, appt.patient_id)
    practice = await db.get(Practice, appt.practice_id)
    allow_cancel = False
    if appt.appointment_type_def_id:
        at = await db.get(AppointmentTypeDef, appt.appointment_type_def_id)
        allow_cancel = bool(at and at.allow_patient_cancel)
    elif appt.appointment_type:
        at = await db.scalar(
            select(AppointmentTypeDef).where(
                AppointmentTypeDef.location_id == appt.location_id,
                AppointmentTypeDef.name == appt.appointment_type,
            )
        )
        allow_cancel = bool(at and at.allow_patient_cancel)

    booking = f"{settings.frontend_url}/appt/{practice_slug(practice.name) if practice else 'book'}"

    if action == "confirm":
        if appt.status == AppointmentStatus.UNCONFIRMED:
            appt.status = AppointmentStatus.CONFIRMED
            meta = dict(appt.meta or {})
            meta.pop("cancel_confirm_pending", None)
            _set_appt_meta(appt, meta)
            await db.flush()
        await db.commit()
        return {
            "status": "confirmed",
            "message": "Your appointment is confirmed. Complete any forms from the link we send you.",
            "booking_link": booking,
            "patient_name": f"{patient.first_name} {patient.last_name}".strip() if patient else "",
            "allow_patient_cancel": allow_cancel,
        }

    if action == "cancel":
        if not allow_cancel:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Patient cancellation is not enabled for this appointment type",
            )
        meta = dict(appt.meta or {})
        if not confirm_cancel and not meta.get("cancel_confirm_pending"):
            meta["cancel_confirm_pending"] = True
            _set_appt_meta(appt, meta)
            await db.commit()
            return {
                "status": "cancel_prompt",
                "message": "Patients will be prompted twice before they cancel. Confirm you want to cancel.",
                "booking_link": booking,
                "patient_name": f"{patient.first_name} {patient.last_name}".strip() if patient else "",
                "allow_patient_cancel": allow_cancel,
                "needs_confirm": True,
            }
        appt.status = AppointmentStatus.CANCELLED
        meta.pop("cancel_confirm_pending", None)
        _set_appt_meta(appt, meta)
        await db.commit()
        return {
            "status": "cancelled",
            "message": "Your appointment has been cancelled.",
            "booking_link": booking,
            "patient_name": f"{patient.first_name} {patient.last_name}".strip() if patient else "",
            "allow_patient_cancel": allow_cancel,
        }

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid action")


async def public_appointment_reminder_info(db: AsyncSession, appointment_id: uuid.UUID) -> dict:
    appt = await db.get(Appointment, appointment_id)
    if appt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    patient = await db.get(Patient, appt.patient_id)
    practice = await db.get(Practice, appt.practice_id)
    allow_cancel = False
    if appt.appointment_type_def_id:
        at = await db.get(AppointmentTypeDef, appt.appointment_type_def_id)
        allow_cancel = bool(at and at.allow_patient_cancel)
    booking = f"{settings.frontend_url}/appt/{practice_slug(practice.name) if practice else 'book'}"
    return {
        "id": str(appt.id),
        "status": appt.status.value if hasattr(appt.status, "value") else str(appt.status),
        "starts_at": appt.starts_at.isoformat(),
        "provider_name": appt.provider_name,
        "appointment_type": appt.appointment_type,
        "patient_name": f"{patient.first_name} {patient.last_name}".strip() if patient else "",
        "allow_patient_cancel": allow_cancel,
        "cancel_confirm_pending": bool((appt.meta or {}).get("cancel_confirm_pending")),
        "booking_link": booking,
        "forms_note": (
            "The form link will not show in the staff preview of the reminder because it is not "
            "connected to an actual appointment. Reminders sent to patients will include forms."
        ),
    }
