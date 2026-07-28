"""Helpers to expose current agent field metadata to the patient chat UI."""
from __future__ import annotations

from typing import Any


def field_meta(field: dict | None) -> dict[str, Any] | None:
    if not field:
        return None
    return {
        "id": field.get("id"),
        "type": field.get("type"),
        "label": field.get("label"),
        "required": bool(field.get("required")),
        "options": field.get("options") or [],
        "placeholder": field.get("placeholder") or "",
    }


def find_field(fields: list[dict], field_id: str | None) -> dict | None:
    if not field_id:
        return None
    return next((f for f in fields if f.get("id") == field_id), None)
