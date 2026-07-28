"""Apply form field sync_target values onto Patient profile columns."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.models.staff import Patient

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


def apply_sync_targets(patient: Patient, fields: list[dict], answers: dict[str, Any]) -> list[str]:
    """Write mapped answers onto the patient record. Returns list of updated sync_target keys."""
    updated: list[str] = []
    for field in fields:
        target = (field.get("sync_target") or "").strip()
        if not target:
            continue
        field_id = field.get("id")
        if not field_id or field_id not in answers:
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
    return updated
