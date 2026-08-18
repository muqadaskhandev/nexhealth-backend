"""Write form/agent answers onto the patient chart and the upcoming visit."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.models.staff import Appointment, Patient
from app.services.field_validation_service import MEDICAL_ALERTS_TYPES, format_medical_alerts_review

_SYNC_MAP: dict[str, str] = {
    "patient.first_name": "first_name",
    "patient.last_name": "last_name",
    "patient.email": "email",
    "patient.phone": "phone",
    "patient.date_of_birth": "dob",
    "patient.address": "address",
    "patient.preferred_language": "language",
}


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def infer_sync_target(field: dict) -> str | None:
    explicit = (field.get("sync_target") or "").strip()
    if explicit:
        return explicit
    ftype = field.get("type") or ""
    label = (field.get("label") or "").strip().lower()
    fid = (field.get("id") or "").strip().lower()
    if ftype in MEDICAL_ALERTS_TYPES:
        return "patient.medical_alerts"
    if ftype == "signature":
        return "patient.signature"
    if ftype == "payment":
        return "patient.payment_preference"
    if ftype == "insurance" or fid == "insurance":
        return "patient.insurance"
    if ftype == "preferred_language":
        return "patient.preferred_language"
    if fid in ("visit-reason", "visit_reason") or ("visit" in label and "reason" in label):
        return "appointment.visit_reason"
    if fid in ("notes", "consent-notes") or "anything else" in label or "comments for the office" in label:
        return "appointment.notes"
    if fid == "married" or "married" in label:
        return "patient.marital_status"
    if "hipaa" in label or fid == "hipaa-consent":
        return "patient.hipaa_consent"
    if "remind" in label or fid == "reminders":
        return "patient.reminders"
    if fid == "signed-on" or (ftype in ("date", "date_entry") and "today" in label and "birth" not in label):
        return "patient.signed_on"
    return None


def patient_chart_snapshot(patient: Patient) -> dict[str, Any]:
    meta = dict(patient.meta or {})
    return {
        "medical_alerts": meta.get("medical_alerts"),
        "medical_alerts_summary": meta.get("medical_alerts_summary") or None,
        "payment_preference": meta.get("payment_preference") or None,
        "intake_signature": meta.get("intake_signature") or None,
        "signed_on": meta.get("signed_on") or None,
        "marital_status": meta.get("marital_status") or None,
        "hipaa_consent": meta.get("hipaa_consent"),
    }


def _set_meta(patient: Patient, **patch: Any) -> None:
    next_meta = {**(patient.meta or {}), **{k: v for k, v in patch.items() if v is not None}}
    patient.meta = next_meta
    flag_modified(patient, "meta")


def _set_appt_meta(appointment: Appointment, **patch: Any) -> None:
    next_meta = {**(appointment.meta or {}), **{k: v for k, v in patch.items() if v is not None}}
    appointment.meta = next_meta
    flag_modified(appointment, "meta")


def _append_note(existing: str, extra: str) -> str:
    extra = extra.strip()
    if not extra:
        return existing
    if extra in existing:
        return existing
    return f"{existing}\n{extra}".strip() if existing else extra


def apply_sync_targets(patient: Patient, fields: list[dict], answers: dict[str, Any]) -> list[str]:
    return apply_intake_sync(patient, fields, answers, appointment=None)


def apply_intake_sync(
    patient: Patient,
    fields: list[dict],
    answers: dict[str, Any],
    *,
    appointment: Appointment | None = None,
) -> list[str]:
    """Write mapped answers onto the patient chart and (when present) the visit."""
    updated: list[str] = []
    visit_notes = str((appointment.meta or {}).get("visit_notes") or "") if appointment else ""

    if appointment is not None:
        pending = dict(patient.meta or {})
        pending_reason = str(pending.get("pending_visit_reason") or "").strip()
        pending_notes = str(pending.get("pending_visit_notes") or "").strip()
        if pending_reason:
            _set_appt_meta(appointment, visit_reason=pending_reason)
            updated.append("appointment.visit_reason")
        if pending_notes:
            visit_notes = _append_note(visit_notes, pending_notes)
            _set_appt_meta(appointment, visit_notes=visit_notes)
            updated.append("appointment.notes")
        if pending_reason or pending_notes:
            next_meta = {k: v for k, v in pending.items() if k not in ("pending_visit_reason", "pending_visit_notes")}
            patient.meta = next_meta
            flag_modified(patient, "meta")

    for field in fields:
        target = infer_sync_target(field)
        field_id = field.get("id")
        if not target or not field_id or field_id not in answers:
            continue
        raw = answers[field_id]
        if raw is None or raw == "":
            continue

        if target == "patient.insurance":
            if isinstance(raw, dict):
                patient.insurance_data = {**(patient.insurance_data or {}), **raw}
            else:
                patient.insurance_data = {**(patient.insurance_data or {}), "summary": str(raw)}
            updated.append(target)
            continue

        if target == "patient.medical_alerts":
            summary = format_medical_alerts_review(raw)
            _set_meta(patient, medical_alerts=raw, medical_alerts_summary=summary)
            updated.append(target)
            continue

        if target == "patient.signature":
            _set_meta(patient, intake_signature=str(raw).strip())
            updated.append(target)
            continue

        if target == "patient.payment_preference":
            label = "Pay at the office" if str(raw) == "pay_at_office" else str(raw).strip()
            _set_meta(patient, payment_preference=label)
            updated.append(target)
            continue

        if target == "patient.marital_status":
            _set_meta(patient, marital_status=str(raw).strip())
            updated.append(target)
            continue

        if target == "patient.hipaa_consent":
            yes = raw is True or str(raw).strip().lower() in ("yes", "true", "y", "1", "checked")
            _set_meta(patient, hipaa_consent=yes)
            updated.append(target)
            continue

        if target == "patient.signed_on":
            parsed = _parse_date(raw)
            _set_meta(patient, signed_on=(parsed.isoformat() if parsed else str(raw).strip()))
            updated.append(target)
            continue

        if target == "patient.reminders":
            items = raw if isinstance(raw, list) else [p.strip() for p in str(raw).split(",") if p.strip()]
            prefs = dict(patient.notification_prefs or {})
            blob = " ".join(str(x).lower() for x in items)
            prefs["sms"] = "text" in blob or "sms" in blob
            prefs["email"] = "email" in blob
            prefs["types"] = prefs.get("types") or {}
            patient.notification_prefs = prefs
            _set_meta(patient, reminder_channels=items)
            updated.append(target)
            continue

        if target == "appointment.visit_reason":
            reason = str(raw).strip()
            if appointment is not None:
                _set_appt_meta(appointment, visit_reason=reason)
            else:
                _set_meta(patient, pending_visit_reason=reason)
            updated.append(target)
            continue

        if target == "appointment.notes":
            visit_notes = _append_note(visit_notes, str(raw).strip())
            if appointment is not None:
                _set_appt_meta(appointment, visit_notes=visit_notes)
            else:
                _set_meta(patient, pending_visit_notes=visit_notes)
            updated.append(target)
            continue

        col = _SYNC_MAP.get(target)
        if not col:
            continue

        if col == "dob":
            parsed = _parse_date(raw)
            if parsed is None:
                continue
            patient.dob = parsed
        else:
            setattr(patient, col, str(raw).strip())
        updated.append(target)

    if appointment is not None and visit_notes and "appointment.notes" in updated:
        _set_appt_meta(appointment, visit_notes=visit_notes)

    return updated


def _digits_only(value: Any) -> str:
    import re

    return re.sub(r"\D", "", str(value or ""))


def _normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_dob(value: Any) -> str:
    # agent/forms validation normalizes DOB as ISO date string (YYYY-MM-DD)
    if value is None or value == "":
        return ""
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    # If it already looks like ISO, keep it; otherwise fall back to parse
    import re

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else ""


def patient_identity_mismatch_message(patient: Patient, field: dict, answers_value: Any) -> str | None:
    """
    Enforce that existing patient identity fields match what's already on file.

    This is intentionally conservative: it only applies to identity fields that
    are typically verified/owned by the existing patient record.
    """
    target = infer_sync_target(field)
    if not target or not isinstance(target, str):
        return None

    # Only enforce these specific patient identity fields.
    if target not in {"patient.email", "patient.phone", "patient.date_of_birth", "patient.dob"}:
        return None

    # If we don't have a value on file yet, don't block intake.
    if target in {"patient.email"}:
        existing = getattr(patient, "email", None)
        if not existing:
            return None
        a = _normalize_email(answers_value)
        b = _normalize_email(existing)
        if a and b and a != b:
            # Do not echo stored PII back to the user (privacy).
            return "Please enter the email we already have on file for you."

    if target in {"patient.phone"}:
        existing = getattr(patient, "phone", None)
        if not existing:
            return None
        a = _digits_only(answers_value)
        b = _digits_only(existing)
        if a and b and a != b:
            # Do not echo stored PII back to the user (privacy).
            return "Please enter the phone number we already have on file for you."

    if target in {"patient.date_of_birth", "patient.dob"}:
        existing = getattr(patient, "dob", None)
        if not existing:
            return None
        a = _normalize_dob(answers_value)
        b = _normalize_dob(existing)
        if a and b and a != b:
            # Do not echo stored PII back to the user (privacy).
            return "Please enter the same date of birth we have on file for you."

    return None


def enforce_existing_patient_identity(patient: Patient, fields: list[dict], answers: dict[str, Any]) -> None:
    """
    Raise ValueError if identity fields provided by an existing patient don't match the record.
    """
    for field in fields:
        fid = field.get("id")
        if not fid or fid not in answers:
            continue
        msg = patient_identity_mismatch_message(patient, field, answers.get(fid))
        if msg:
            raise ValueError(msg)
