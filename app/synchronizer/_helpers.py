"""Shared helpers for EHR adapters."""
from __future__ import annotations

from typing import Any

from app.synchronizer.types import FormChartPayload, FormPushResult


def require_fields(credentials: dict[str, Any], fields: list[str]) -> list[str]:
    errors: list[str] = []
    for field in fields:
        if not str(credentials.get(field, "")).strip():
            errors.append(f"Missing required field: {field}")
    return errors


def form_push_unsupported(ehr_label: str) -> FormPushResult:
    return FormPushResult(
        ok=False,
        message=f"Form chart sync is not implemented for {ehr_label} yet. Use Mark as synced after filing manually.",
    )


def format_form_answers_text(payload: FormChartPayload) -> str:
    lines = [
        f"NexHealth form: {payload.form_name}",
        f"Patient: {payload.patient_name}" if payload.patient_name else "",
        f"Submitted: {payload.submitted_at_iso}" if payload.submitted_at_iso else "",
        "",
        "Answers:",
    ]
    for key, value in (payload.answers or {}).items():
        if isinstance(value, (list, dict)):
            import json

            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = str(value)
        lines.append(f"- {key}: {rendered}")
    return "\n".join(line for line in lines if line is not None)
