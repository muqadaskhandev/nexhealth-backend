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
            if appointment is not None:
                _set_appt_meta(appointment, visit_reason=str(raw).strip())
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
